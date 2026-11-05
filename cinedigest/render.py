"""Page renderer: Snapshot → Jinja2 context → templates/index.html.j2 → one HTML page per window day."""
from __future__ import annotations

import logging
import os
from dataclasses import replace
from datetime import date, timedelta

from jinja2 import Environment, PackageLoader

from . import config, posters
from .model import Screening, Snapshot, VENUES, select

log = logging.getLogger(__name__)

INDEX_FILENAME = "index.html"

_ENV: Environment | None = None


def _template():
    global _ENV
    if _ENV is None:
        _ENV = Environment(
            loader=PackageLoader("cinedigest", "templates"),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _ENV.get_template("index.html.j2")


def page_name(day: date) -> str:
    """The static page of a window day, flat in docs/ next to index.html."""
    return f"{day.isoformat()}.html"


def _window_days(snapshot: Snapshot) -> list[date]:
    """The snapshot's window, start..end inclusive (a saved snapshot may re-render)."""
    days: list[date] = []
    day = snapshot.window_start
    while day <= snapshot.window_end:
        days.append(day)
        day += timedelta(days=1)
    return days


def _normalize_genres(screenings: list[Screening]) -> list[Screening]:
    """Copies with extra.genres as a list: outcinema stores a comma string, the
    template slices [:3] on a list. Anything already a list passes unchanged."""
    copies: list[Screening] = []
    for s in screenings:
        x = dict(s.extra or {})
        genres = x.get("genres")
        if isinstance(genres, str):
            genre_list = [part.strip() for part in genres.split(",") if part.strip()]
            x["genres"] = genre_list or None
            s = replace(s, extra=x)
        copies.append(s)
    return copies


def _attach_posters(screenings: list[Screening], urls: dict[str, str]) -> list[Screening]:
    """Render-only copies carrying extra.poster; the snapshot itself never stores the URL."""
    if not urls:
        return screenings
    copies: list[Screening] = []
    for s in screenings:
        key = posters.film_key(s.title, posters.film_year((s.extra or {}).get("year")))
        url = urls.get(key) if key else None
        if url:
            x = dict(s.extra or {})
            x["poster"] = url
            s = replace(s, extra=x)
        copies.append(s)
    return copies


def render_context(snapshot: Snapshot, poster_urls: dict[str, str] | None = None) -> dict:
    """The context documented in templates/index.html.j2 (minus the per-page day_index).

    Engine fact: `select(..., evening_only=True)` screenings go into a LIST, not a
    set — Screening is a frozen dataclass with an unhashable dict field (extra),
    so a set of Screenings cannot exist; membership works by equality instead.
    """
    screenings = _attach_posters(_normalize_genres(list(snapshot.screenings)), poster_urls or {})
    days = _window_days(snapshot)
    all_days = list(select(screenings, days, evening_only=False).items())
    evening = [s for rows in select(screenings, days, evening_only=True).values() for s in rows]
    return {
        "generated_at": snapshot.generated_at,
        "today": snapshot.window_start,
        "days": all_days,
        "evening": evening,
        "statuses": snapshot.statuses,
        "venues": VENUES,
        "repo_url": os.environ.get(config.REPO_URL_ENV) or None,
        "json_name": config.SCREENINGS_FILENAME,
        "posters": bool(poster_urls),
        "tmdb_site_url": config.TMDB_SITE_URL,
        "tmdb_notice": config.TMDB_NOTICE,
        "tmdb_logo": config.TMDB_LOGO_FILENAME,
    }


def render_pages(snapshot: Snapshot, poster_urls: dict[str, str] | None = None) -> dict[str, str]:
    """filename -> HTML: index.html (= the first window day) plus one page per window day.
    Every artifact's size is logged; a page at or over the budget warns."""
    context = render_context(snapshot, poster_urls)
    pages: dict[str, str] = {}
    for index, (day, _rows) in enumerate(context["days"]):
        html = _template().render(**context, day_index=index)
        if index == 0:
            pages[INDEX_FILENAME] = html
        pages[page_name(day)] = html
    for name, html in pages.items():
        size = len(html.encode("utf-8"))
        log.info("%s: %d bytes", name, size)
        if size >= config.RENDER_WARN_BYTES:
            log.warning("%s is %d bytes (threshold %d) — page weight budget exceeded",
                        name, size, config.RENDER_WARN_BYTES)
    return pages


def render(snapshot: Snapshot, poster_urls: dict[str, str] | None = None) -> str:
    """index.html — the first window day. Other days: render_pages()."""
    return render_pages(snapshot, poster_urls)[INDEX_FILENAME]
