"""Posters via TMDB (api.themoviedb.org/3, developer tier — see docs/tmdb-image-use.md).
One lookup per distinct film (normalised title + year) of the snapshot; the answer is cached
in docs/posters.json and the local byte copy goes to docs/posters/, both re-validated under
the ≤6-month cache clause; docs/posters-overrides.json pins or suppresses a film by hand.
Adapter shape: `fetch()` and `download_files()` are the only networked functions; planning
(`plan`, `download_plan`) and matching (`choose`, `parse`) are pure and offline-testable.
The page serves posters/<basename> only when the file is on disk and within the retention
limit — a missing or expired file never falls back to the CDN URL, no poster renders instead.
Deleting docs/posters.json and docs/posters/ purges the served poster cache in one step.
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
_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
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


def films(screenings, year_hints: dict[str, int] | None = None) -> dict[str, Film]:
    """Distinct films carrying a year, first-seen order; domkino's original_title is kept
    as soon as any row of the film has one."""
    out: dict[str, Film] = {}
    for s in screenings:
        x = s.extra or {}
        year = film_year(x.get("year"))
        if year is None and year_hints is not None:
            year = film_year(year_hints.get(norm(s.title)))
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
            "delete this file and the docs/posters/ folder to purge the served poster cache; "
            "entries older than "
            f"{config.TMDB_CACHE_MAX_AGE_DAYS} days are dropped on every save and image files "
            f"share the same retention limit (see file_downloaded_at)"
        ),
        "films": dict(sorted(prune(entries, today).items())),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if file.is_file() and file.read_text(encoding="utf-8") == text:
        return False
    file.parent.mkdir(parents=True, exist_ok=True)
    temp = file.with_name(f".{file.name}.{os.getpid()}.part")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, file)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
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
def _country_fields(movie: dict, today: date) -> dict:
    """Only a verified movie-details body may reach this parser; never search results."""
    countries = movie.get("production_countries")
    if not isinstance(countries, list):
        return {}
    names = []
    for country in countries:
        name = country.get("name") if isinstance(country, dict) else None
        if isinstance(name, str) and name.strip():
            names.append(name)
    return {
        "country": names,
        "country_at": today.isoformat(),
        "country_via": f"tmdb:{movie['id']}",
    }


def fetch_details(http, token: str, entries: dict[str, dict], today: date) -> dict[str, dict]:
    """Fetch countries for already-confident identities, at most one details request per film.
    The caller supplies films admitted to the lookup budget; this defensive cap also bounds
    direct calls. Details failures do not discard successfully resolved poster metadata."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    out: dict[str, dict] = {}
    failures = 0
    for key, entry in list(entries.items())[: config.TMDB_MAX_LOOKUPS_PER_RUN]:
        tmdb_id = entry.get("tmdb_id")
        if not isinstance(tmdb_id, int) or isinstance(tmdb_id, bool) or tmdb_id <= 0:
            continue
        try:
            body = http.get(
                f"{config.TMDB_API_URL}/movie/{tmdb_id}",
                params={"language": config.TMDB_LANGUAGE},
                headers=headers, venue=ID, label=key + "@details",
            )
            movie = _json(body)
            if not isinstance(movie, dict) or movie.get("id") != tmdb_id:
                raise ValueError("invalid or mismatched movie details")
            out[key] = _country_fields(movie, today)
        except (HttpError, ValueError) as exc:
            failures += 1
            log.warning("posters: %s details: %s", key, exc)
            if failures >= config.TMDB_FAILURE_LIMIT:
                log.warning("posters: %d failed details — remaining countries wait",
                            failures)
                break
    return out


def country_evidence(entries: dict) -> list[dict]:
    """Pure reader of load_cache()'s film-key mapping, NOT the JSON envelope."""
    out = []
    for entry in entries.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("title"), str):
            continue
        country = entry.get("country")
        if not isinstance(country, (str, list)) or not country:
            continue
        if not any(isinstance(name, str) and name.strip()
                   for name in (country if isinstance(country, list) else [country])):
            continue
        out.append({
            "title": entry["title"], "year": entry.get("year"),
            "country": list(country) if isinstance(country, list) else country,
            "source": entry.get("country_via") or f"tmdb:{entry.get('tmdb_id')}",
        })
    return out


def identity_evidence(entries: dict) -> list[dict]:
    """Pure dated identities, including entries without country evidence."""
    out = []
    for entry in entries.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("title"), str):
            continue
        year = film_year(entry.get("year"))
        if year is None:
            continue
        out.append({
            "title": entry["title"], "year": year, "country": "",
            "source": entry.get("country_via") or f"tmdb:{entry.get('tmdb_id')}",
        })
    return out

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
                out[film.key].update(_country_fields(movie, today))
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


# ---- lookups for the renderer (offline reads, no network) -------------------------------
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


def poster_files(wanted: dict[str, Film], entries: dict[str, dict], overrides: dict,
                 today: date, posters_dir) -> dict[str, str]:
    """film key -> 'posters/<basename>' for every film of the snapshot with a ready LOCAL copy;
    a missing or expired file renders NO poster — no CDN URL ever leaves this module."""
    ready: dict[str, str] = {}
    for key in wanted:
        name = _ready_name(key, entries, overrides, today, posters_dir)
        if name:
            ready[key] = f"{config.POSTERS_DIRNAME}/{name}"
    return ready


def file_name(poster_path) -> str | None:
    """Validated local basename of a poster path ('/x.jpg' → 'x.jpg'): lookup and writes only
    ever combine it with docs/posters/, so directory tricks in a hand-written or hostile path
    can never move a poster file outside the folder — an unsafe name is rejected outright."""
    if not isinstance(poster_path, str):
        return None
    name = Path(poster_path).name  # strips any directory part
    return name if _SAFE_FILE_RE.fullmatch(name) else None


def file_recent(downloaded, today: date) -> bool:
    """Byte-retention clause: file_downloaded_at no older than TMDB_CACHE_MAX_AGE_DAYS —
    the SAME ≤6-month rule as the metadata; an undated or future-dated file is expired."""
    downloaded_at = _parse_date(downloaded)
    return downloaded_at is not None and 0 <= (today - downloaded_at).days <= config.TMDB_CACHE_MAX_AGE_DAYS


def _ready_name(key, entries: dict[str, dict], overrides: dict, today: date, posters_dir) -> str | None:
    """The local file is ready to serve: the effective poster path validates to a safe name,
    the entry records exactly that name within the retention limit, and the file is really
    on disk under docs/posters/ (a symlink is never ours — it can be a traversal hole)."""
    name = file_name(poster_path(key, entries, overrides))
    if name is None:
        return None
    entry = entries.get(key)
    if not entry or entry.get("file") != name or not file_recent(entry.get("file_downloaded_at"), today):
        return None
    file = Path(posters_dir) / name
    if file.is_symlink() or not file.is_file():
        return None
    return name


def cached_urls(screenings, docs_dir, today: date,
                year_hints: dict[str, int] | None = None) -> dict[str, str]:
    """Offline render path: the local poster files the committed cache + overrides give for a
    snapshot — freshness re-checked against `today` at every render, never from mere existence."""
    docs = Path(docs_dir)
    return poster_files(
        films(screenings, year_hints),
        load_cache(docs / config.POSTERS_FILENAME),
        load_overrides(docs / config.POSTER_OVERRIDES_FILENAME),
        today,
        docs / config.POSTERS_DIRNAME,
    )


# ---- byte plan (offline reads, no network) -----------------------------------------------
def download_plan(screenings, entries: dict[str, dict], overrides: dict, today: date, posters_dir,
                  year_hints: dict[str, int] | None = None) -> list[str]:
    """Poster paths whose local copy still has to be fetched: the entry records no such file,
    its byte age is expired/undated, or the file is gone from disk. Distinct poster paths only
    (several films may share one file) in order of first need; unsafe paths never reach here."""
    due: list[str] = []
    seen: set[str] = set()
    for key in films(screenings, year_hints):
        path = poster_path(key, entries, overrides)
        if not path or path in seen or file_name(path) is None:
            continue
        seen.add(path)
        if not _ready_name(key, entries, overrides, today, posters_dir):
            due.append(path)
    return due


# ---- byte stage (network) ---------------------------------------------------------------
def download_files(http, paths: list[str], posters_dir) -> dict[str, str]:
    """Fetch the byte copy for every distinct safe poster path (image CDN, no key, no
    transformation — image_url() gives the URL) and publish it ATOMICALLY: temp file plus
    rename, so a failed or partial download can never replace usable existing bytes. Stops
    after TMDB_DOWNLOAD_FAILURE_LIMIT failures (publication errors count the same); anything
    over TMDB_MAX_DOWNLOADS_PER_RUN waits for the next run. Returns poster_path -> basename."""
    stored: dict[str, str] = {}
    over = len(paths) - config.TMDB_MAX_DOWNLOADS_PER_RUN
    if over > 0:
        log.info("posters: %d posters over the per-run download budget wait for the next run", over)
    failures = 0
    for path in paths[: config.TMDB_MAX_DOWNLOADS_PER_RUN]:
        name = file_name(path)
        if name is None:  # defensive: download_plan already rejected unsafe paths
            continue
        try:
            data = http.get_bytes(image_url(path), venue=ID, label=name)
        except HttpError as exc:
            failures += 1
            log.warning("posters: %s: %s", path, exc)
            if failures >= config.TMDB_DOWNLOAD_FAILURE_LIMIT:
                log.warning("posters: %d failed downloads — the remaining posters wait for the next run",
                            failures)
                break
            continue
        if _publish(posters_dir, name, data) is None:
            failures += 1
            if failures >= config.TMDB_DOWNLOAD_FAILURE_LIMIT:
                log.warning("posters: %d failed stores — the remaining posters wait for the next run",
                            failures)
                break
            continue
        stored[path] = name
    return stored


def _publish(posters_dir, name: str, data: bytes) -> str | None:
    """Write data as <posters_dir>/<name> via a hidden temp file + os.replace; None (and no
    leftovers) on any error — a file already on disk keeps its usable bytes untouched."""
    file = Path(posters_dir) / name
    temp = Path(posters_dir) / f".{name}.{os.getpid()}.part"
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(data)
        os.replace(temp, file)
    except OSError as exc:
        log.warning("posters: %s: %d bytes not stored: %s", name, len(data), exc)
        try:
            temp.unlink()
        except OSError:
            pass
        return None
    return name


# ---- cleanup ----------------------------------------------------------------------------
def cleanup(posters_dir, entries: dict[str, dict], today: date) -> list[str]:
    """Delete expired and orphaned image files under docs/posters/: a file survives only while
    SOME live entry names it via `file` within the byte-retention limit (several entries may
    reference one file — one fresh date is enough). Unsafe names are never touched, and only
    plain files inside docs/posters/ can be removed; the caller passes its live entries."""
    removed: list[str] = []
    dirpath = Path(posters_dir)
    if not dirpath.is_dir():
        return removed
    for file in sorted(dirpath.iterdir()):
        if not file.is_file():
            continue  # a stray directory is left for the owner to deal with
        name = file.name
        if not _SAFE_FILE_RE.fullmatch(name):
            log.warning("posters: skipping unsafe name %r under %s", name, dirpath)
            continue
        if any(entry.get("file") == name and file_recent(entry.get("file_downloaded_at"), today)
               for entry in entries.values()):
            continue
        file.unlink()
        removed.append(name)
    if removed:
        log.info("posters: pruned %d stale image file(s) under %s", len(removed), dirpath)
    return removed


# ---- orchestration --------------------------------------------------------------------
def _carry_file_fields(parsed: dict[str, dict], previous: dict[str, dict]) -> None:
    """A metadata refresh must not touch the byte age: an entry whose poster_path stayed the
    same carries over the previous record of the downloaded file — kept, never renewed."""
    for key, entry in parsed.items():
        old = previous.get(key)
        if not isinstance(old, dict) or old.get("poster_path") != entry.get("poster_path"):
            continue
        for field in ("file", "file_downloaded_at"):
            if field in old:
                entry[field] = old[field]


def _attach_bytes(cache: dict[str, dict], wanted: dict[str, Film], overrides: dict,
                  stored: dict[str, str], today: date) -> int:
    """Record the downloaded bytes on every wanted entry that references them: the shared-file
    dedupe lands the SAME `file` and `file_downloaded_at` on each referencing entry. A film the
    bytes came to through a hand pin without an entry gets a record one (poster_path stays
    None, via='override') — hand data stays hand data, the file just becomes accountable."""
    annotated = 0
    for key, film in wanted.items():
        path = poster_path(key, cache, overrides)
        name = stored.get(path) if path else None
        if not name:
            continue
        entry = cache.get(key)
        if entry is None:
            entry = {"title": film.title, "year": film.year, "tmdb_id": None, "tmdb_title": None,
                     "poster_path": None, "resolved_at": today.isoformat(), "via": "override"}
            cache[key] = entry
        entry["file"] = name
        entry["file_downloaded_at"] = today.isoformat()
        annotated += 1
    return annotated


def resolve(screenings, *, http, out_dir, today: date, token: str | None = None,
            year_hints: dict[str, int] | None = None) -> dict[str, str]:
    """Look up what the cache lacks, download what still has no local copy, persist
    docs/posters.json + docs/posters/, return film key -> 'posters/<basename>'.
    Without a token (env unset) nothing is fetched and the cache as it stands is used —
    yet expired entries and stale image files are still pruned, the served docs stay honest."""
    docs = Path(out_dir) / config.DOCS_DIRNAME
    screenings = tuple(screenings)
    cache_path = docs / config.POSTERS_FILENAME
    posters_dir = docs / config.POSTERS_DIRNAME
    overrides = load_overrides(docs / config.POSTER_OVERRIDES_FILENAME)
    cache = load_cache(cache_path)
    wanted = films(screenings, year_hints)
    if token is None:
        token = os.environ.get(config.TMDB_READ_TOKEN_ENV) or None
    if not token:
        log.info("posters: %s is not set — TMDB lookups skipped, %d cached films reused",
                 config.TMDB_READ_TOKEN_ENV, len(cache))
    due: list[Film] = []
    stored: dict[str, str] = {}
    if token:
        due = plan(wanted, cache, overrides, today)
        if due:
            raw = fetch(http, token, due, overrides)
            parsed = parse(raw, due, overrides, today)
            _carry_file_fields(parsed, cache)
            cache.update(parsed)
            detail_entries = {
                film.key: cache[film.key] for film in due
                if film.key in cache
                and not (film.key in parsed
                         and isinstance(overrides.get(film.key), dict)
                         and overrides[film.key].get("tmdb_id"))
            }
            for key, fields in fetch_details(http, token, detail_entries, today).items():
                cache[key].update(fields)
    cache = prune(cache, today)
    if token:
        stored = download_files(http, download_plan(screenings, cache, overrides, today, posters_dir,
                                                   year_hints),
                                posters_dir)
        _attach_bytes(cache, wanted, overrides, stored, today)
    pruned_files = cleanup(posters_dir, cache, today)
    changed = save_cache(cache_path, cache, today)
    ready = poster_files(wanted, cache, overrides, today, posters_dir)
    log.info("posters: %d films in the window, %d looked up, %d downloaded, %d with a poster, "
             "%d image file(s) pruned, cache %s",
             len(wanted), len(due), len(stored), len(ready), len(pruned_files),
             "updated" if changed else "unchanged")
    return ready


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
