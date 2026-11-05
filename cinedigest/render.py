"""Page renderer: Snapshot → Jinja2 context → templates/index.html.j2 → index.html."""
from __future__ import annotations

import logging
import os
from dataclasses import replace
from datetime import date, timedelta

from jinja2 import Environment, PackageLoader

from . import config
from .model import Screening, Snapshot, VENUES, select

log = logging.getLogger(__name__)

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


def render_context(snapshot: Snapshot) -> dict:
    """The context documented in templates/index.html.j2.

    Engine fact: `select(..., evening_only=True)` screenings go into a LIST, not a
    set — Screening is a frozen dataclass with an unhashable dict field (extra),
    so a set of Screenings cannot exist; membership works by equality instead.
    """
    screenings = _normalize_genres(list(snapshot.screenings))
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
    }


def render(snapshot: Snapshot) -> str:
    """The rendered index.html; the size is logged, a too-heavy page warns."""
    html = _template().render(**render_context(snapshot))
    size = len(html.encode("utf-8"))
    log.info("index.html: %d bytes", size)
    if size >= config.RENDER_WARN_BYTES:
        log.warning(
            "index.html is %d bytes (threshold %d) — page weight budget exceeded",
            size, config.RENDER_WARN_BYTES,
        )
    return html
