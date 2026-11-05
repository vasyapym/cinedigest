"""Posters via TMDB (api.themoviedb.org/3, developer tier — see docs/tmdb-image-use.md).
One lookup per distinct film (normalised title + year) of the snapshot; the answer is cached
in docs/posters.json and re-resolved under the ≤6-month cache clause; docs/posters-overrides.json
pins or suppresses a film by hand. Adapter shape: `fetch()` is the only networked function,
planning (`plan`) and matching (`choose`, `parse`) are pure and offline-testable.
Deleting docs/posters.json purges every cached TMDB datum in one step.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config
from .http import HttpError

log = logging.getLogger(__name__)

ID = "tmdb"  # archive-sink folder of the raw answers: snapshots/<run>/tmdb/<label>
ANY_SUFFIX = "@any"  # label suffix of the year-less retry
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACES_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
_MISSING = object()


@dataclass(frozen=True)
class Film:
    key: str
    title: str
    year: int
    original_title: str | None = None


# ---- keys -----------------------------------------------------------------------------
def norm(title) -> str:
    """Matching form of a title: lower-case, ё→е, punctuation → space, single spaces."""
    text = str(title or "").lower().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    return _SPACES_RE.sub(" ", text).strip()


def film_year(value) -> int | None:
    """extra.year as an int: accepts 2025, "2025", "2024–2025" (first year wins)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    match = _YEAR_RE.search(str(value))
    return int(match.group(1)) if match else None


def film_key(title, year) -> str | None:
    name = norm(title)
    if not name or year is None:
        return None
    return f"{name}|{int(year)}"


def films(screenings) -> dict[str, Film]:
    """Distinct films carrying a year, first-seen order; domkino's original_title is kept
    as soon as any row of the film has one."""
    out: dict[str, Film] = {}
    for s in screenings:
        x = s.extra or {}
        year = film_year(x.get("year"))
        key = film_key(s.title, year)
        if key is None:
            continue
        original = str(x.get("original_title") or "").strip() or None
        previous = out.get(key)
        if previous is None:
            out[key] = Film(key, s.title.strip(), year, original)
        elif previous.original_title is None and original:
            out[key] = Film(key, previous.title, year, original)
    return out


# ---- cache and overrides --------------------------------------------------------------
def load_cache(path) -> dict[str, dict]:
    data = _read_json(path)
    entries = data.get("films") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {key: dict(value) for key, value in entries.items() if isinstance(value, dict)}


def save_cache(path, entries: dict[str, dict], today: date) -> bool:
    """Write the pruned cache; False when the file already holds this content (no noisy commit)."""
    file = Path(path)
    payload = {
        "_notice": config.TMDB_NOTICE,
        "_source": config.TMDB_SITE_URL,
        "_purge": (
            "delete this file to remove every cached TMDB datum; entries older than "
            f"{config.TMDB_CACHE_MAX_AGE_DAYS} days are dropped on every save"
        ),
        "films": dict(sorted(prune(entries, today).items())),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if file.is_file() and file.read_text(encoding="utf-8") == text:
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    return True


def prune(entries: dict[str, dict], today: date) -> dict[str, dict]:
    """Entries resolved within TMDB_CACHE_MAX_AGE_DAYS; undated or future-dated ones go too."""
    kept: dict[str, dict] = {}
    for key, entry in entries.items():
        resolved = _parse_date(entry.get("resolved_at"))
        if resolved is None or not 0 <= (today - resolved).days <= config.TMDB_CACHE_MAX_AGE_DAYS:
            continue
        kept[key] = entry
    return kept


def load_overrides(path) -> dict[str, dict | None]:
    """key -> null | {"tmdb_id": N} | {"poster_path": "/x.jpg" | null}; keys are normalised,
    so the owner may write «Морозко|1964»; «_…» keys are documentation."""
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict | None] = {}
    for raw_key, value in data.items():
        if raw_key.startswith("_"):
            continue
        if value is not None and not isinstance(value, dict):
            log.warning("posters: override %r ignored — expected null or an object", raw_key)
            continue
        title, sep, year = raw_key.rpartition("|")
        key = film_key(title, film_year(year)) if sep else None
        out[key or raw_key] = value
    return out


# ---- planning (pure) ------------------------------------------------------------------
def fresh(entry: dict, today: date) -> bool:
    resolved = _parse_date(entry.get("resolved_at"))
    if resolved is None:
        return False
    limit = config.TMDB_REFRESH_DAYS if entry.get("poster_path") else config.TMDB_MISS_RETRY_DAYS
    return 0 <= (today - resolved).days < limit


def plan(wanted: dict[str, Film], cache: dict[str, dict], overrides: dict, today: date) -> list[Film]:
    """Films that need a lookup this run: unknown, expired, or pinned to an id not yet resolved."""
    due: list[Film] = []
    for key, film in wanted.items():
        override = overrides.get(key, _MISSING)
        entry = cache.get(key)
        if override is None or (override is not _MISSING and "poster_path" in override):
            continue  # settled by hand, no network
        if override is not _MISSING:
            tmdb_id = override.get("tmdb_id")
            if not tmdb_id:
                continue  # malformed pin: nothing to resolve
            if entry and entry.get("tmdb_id") == tmdb_id and fresh(entry, today):
                continue
            due.append(film)
        elif entry is None or not fresh(entry, today):
            due.append(film)
    over = len(due) - config.TMDB_MAX_LOOKUPS_PER_RUN
    if over > 0:
        log.info("posters: %d films over the per-run budget wait for the next run", over)
    return due[: config.TMDB_MAX_LOOKUPS_PER_RUN]


# ---- network --------------------------------------------------------------------------
def fetch(http, token: str, due: list[Film], overrides: dict | None = None) -> list[tuple[str, str]]:
    """Raw TMDB answers as (label, body): label = film key; the year-less retry (only when the
    first search is empty) is labelled key + '@any'; an id pin fetches /movie/{id} under the key.
    Stops after TMDB_FAILURE_LIMIT failed lookups (a 429 is a failure, never retried here)."""
    overrides = overrides or {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    search_url = f"{config.TMDB_API_URL}/search/movie"
    raw: list[tuple[str, str]] = []
    failures = 0
    for film in due:
        override = overrides.get(film.key)
        try:
            if isinstance(override, dict) and override.get("tmdb_id"):
                body = http.get(
                    f"{config.TMDB_API_URL}/movie/{int(override['tmdb_id'])}",
                    params={"language": config.TMDB_LANGUAGE},
                    headers=headers, venue=ID, label=film.key,
                )
                raw.append((film.key, body))
                continue
            body = http.get(
                search_url,
                params={"query": film.title, "year": film.year,
                        "language": config.TMDB_LANGUAGE, "include_adult": "false"},
                headers=headers, venue=ID, label=film.key,
            )
            raw.append((film.key, body))
            if not results(body):
                label = film.key + ANY_SUFFIX
                body = http.get(
                    search_url,
                    params={"query": film.original_title or film.title,
                            "language": config.TMDB_LANGUAGE, "include_adult": "false"},
                    headers=headers, venue=ID, label=label,
                )
                raw.append((label, body))
        except HttpError as exc:
            failures += 1
            log.warning("posters: %s: %s", film.key, exc)
            if failures >= config.TMDB_FAILURE_LIMIT:
                log.warning("posters: %d failed lookups — the remaining films wait for the next run",
                            failures)
                break
    return raw


# ---- matching (pure) ------------------------------------------------------------------
def results(body) -> list[dict]:
    data = _json(body)
    items = data.get("results") if isinstance(data, dict) else None
    return [item for item in (items or []) if isinstance(item, dict)]


def choose(candidates: list[dict], film: Film) -> dict | None:
    """Precision first: an exact normalised title/original-title match within ±1 year
    (exact year, then popularity, break ties); else a LONE same-year answer; else None."""
    wanted = {norm(film.title)}
    if film.original_title:
        wanted.add(norm(film.original_title))
    wanted.discard("")
    best: dict | None = None
    best_rank: tuple | None = None
    for movie in candidates:
        year = _release_year(movie.get("release_date"))
        if year is None or abs(year - film.year) > 1:
            continue
        names = {norm(movie.get("title")), norm(movie.get("original_title"))}
        if not names & wanted:
            continue
        rank = (year == film.year, _float(movie.get("popularity")))
        if best_rank is None or rank > best_rank:
            best, best_rank = movie, rank
    if best is None and len(candidates) == 1:
        lone = candidates[0]
        if _release_year(lone.get("release_date")) == film.year:
            best = lone
    return best


def parse(raw: list[tuple[str, str]], due: list[Film], overrides: dict | None = None,
          today: date | None = None) -> dict[str, dict]:
    """key -> cache entry for every film that got an answer; films without a body are left
    untouched (the cache keeps whatever it had)."""
    overrides = overrides or {}
    today = today or date.today()
    bodies = dict(raw)
    out: dict[str, dict] = {}
    for film in due:
        override = overrides.get(film.key)
        if isinstance(override, dict) and override.get("tmdb_id"):
            movie = _json(bodies.get(film.key))
            if isinstance(movie, dict) and movie.get("id") == override["tmdb_id"]:
                out[film.key] = _entry(film, movie, today, "override")
            continue
        if film.key not in bodies:
            continue
        for label, via in ((film.key, "year"), (film.key + ANY_SUFFIX, "any")):
            if label not in bodies:
                continue
            movie = choose(results(bodies[label]), film)
            if movie is not None:
                out[film.key] = _entry(film, movie, today, via)
                break
        else:
            out[film.key] = _miss(film, today)
    return out


# ---- lookups for the renderer (pure) --------------------------------------------------
def image_url(poster_path: str) -> str:
    return f"{config.TMDB_IMAGE_BASE_URL}{config.TMDB_POSTER_SIZE}{poster_path}"


def poster_path(key: str, cache: dict[str, dict], overrides: dict) -> str | None:
    if key in overrides:
        override = overrides[key]
        if override is None:
            return None
        if "poster_path" in override:
            return override["poster_path"] or None
        entry = cache.get(key)
        if entry and entry.get("tmdb_id") == override.get("tmdb_id"):
            return entry.get("poster_path") or None
        return None
    entry = cache.get(key)
    return (entry.get("poster_path") or None) if entry else None


def poster_urls(screenings, cache: dict[str, dict], overrides: dict | None = None) -> dict[str, str]:
    """film key -> full image URL for every film of the snapshot with a known poster."""
    overrides = overrides or {}
    urls: dict[str, str] = {}
    for key in films(screenings):
        path = poster_path(key, cache, overrides)
        if path:
            urls[key] = image_url(path)
    return urls


def cached_urls(screenings, docs_dir) -> dict[str, str]:
    """Offline: the URLs the committed cache + overrides give for a snapshot (render path)."""
    docs = Path(docs_dir)
    return poster_urls(
        screenings,
        load_cache(docs / config.POSTERS_FILENAME),
        load_overrides(docs / config.POSTER_OVERRIDES_FILENAME),
    )


# ---- orchestration --------------------------------------------------------------------
def resolve(screenings, *, http, out_dir, today: date, token: str | None = None) -> dict[str, str]:
    """Look up what the cache lacks, persist docs/posters.json, return key -> URL.
    Without a token (env unset) nothing is fetched and the cache as it stands is used."""
    docs = Path(out_dir) / config.DOCS_DIRNAME
    cache_path = docs / config.POSTERS_FILENAME
    overrides = load_overrides(docs / config.POSTER_OVERRIDES_FILENAME)
    cache = load_cache(cache_path)
    wanted = films(screenings)
    if token is None:
        token = os.environ.get(config.TMDB_READ_TOKEN_ENV) or None
    if not token:
        log.info("posters: %s is not set — TMDB lookups skipped, %d cached films reused",
                 config.TMDB_READ_TOKEN_ENV, len(cache))
        return poster_urls(screenings, cache, overrides)
    due = plan(wanted, cache, overrides, today)
    if due:
        raw = fetch(http, token, due, overrides)
        cache.update(parse(raw, due, overrides, today))
    cache = prune(cache, today)
    changed = save_cache(cache_path, cache, today)
    hits = sum(1 for key in wanted if poster_path(key, cache, overrides))
    log.info("posters: %d films in the window, %d looked up, %d with a poster, cache %s",
             len(wanted), len(due), hits, "updated" if changed else "unchanged")
    return poster_urls(screenings, cache, overrides)


# ---- helpers --------------------------------------------------------------------------
def _read_json(path):
    file = Path(path)
    if not file.is_file():
        return None
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("posters: could not read %s: %s", file, exc)
        return None


def _json(body):
    if body is None:
        return None
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        return None


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _release_year(value) -> int | None:
    return film_year(str(value)[:4]) if value else None


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _entry(film: Film, movie: dict, today: date, via: str) -> dict:
    path = movie.get("poster_path")
    return {
        "title": film.title,
        "year": film.year,
        "tmdb_id": movie.get("id"),
        "tmdb_title": movie.get("title"),
        "poster_path": path if isinstance(path, str) and path.startswith("/") else None,
        "resolved_at": today.isoformat(),
        "via": via,
    }


def _miss(film: Film, today: date) -> dict:
    return {
        "title": film.title, "year": film.year, "tmdb_id": None, "tmdb_title": None,
        "poster_path": None, "resolved_at": today.isoformat(), "via": "miss",
    }
