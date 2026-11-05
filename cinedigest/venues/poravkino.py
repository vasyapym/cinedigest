"""Художественный (poravkino.ru): JSON schedule API, one request per window day."""
from __future__ import annotations

import json
import logging
from datetime import date, timezone

from .. import config
from ..model import VENUES, Screening, synthetic_id
from . import load_json, parse_iso, text_or_none, to_int

log = logging.getLogger(__name__)

ID = "poravkino"
NAME = VENUES[ID]
DAILY = True


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    raw: list[tuple[str, str]] = []
    for day in days:
        label = day.isoformat()
        body = http.get(config.PORAVKINO_SCHEDULE_URL, params={"date": label}, venue=ID, label=label)
        raw.append((label, body))
    return raw


def parse(raw: list[tuple[str, str]], days: list[date]) -> list[Screening]:
    wanted = set(days)
    seen: set[str] = set()
    out: list[Screening] = []
    for label, body in raw:
        data = load_json(body, label, ID)
        if not isinstance(data, list):
            raise ValueError(f"{ID} {label}: expected a JSON list of movies, got {type(data).__name__}")
        source_url = f"{config.PORAVKINO_SCHEDULE_URL}?date={label}"
        for movie in data:
            if not isinstance(movie, dict):
                continue
            performances = movie.get("performances")
            if not isinstance(performances, list):
                continue
            for performance in performances:
                if not isinstance(performance, dict):
                    continue
                screening = _screening(movie, performance, source_url)
                if screening is None or screening.day not in wanted or screening.source_id in seen:
                    continue
                seen.add(screening.source_id)
                out.append(screening)
    return out


def legit_empty(body: str) -> bool:
    """HTTP 200 with `[]` (or movies whose `performances` lists are explicitly empty)."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return False
    if not isinstance(data, list):
        return False
    if not data:
        return True
    for movie in data:
        if not isinstance(movie, dict):
            return False
        performances = movie.get("performances")
        if not isinstance(performances, list) or performances:
            return False
    return True


def _screening(movie: dict, performance: dict, source_url: str) -> Screening | None:
    if not performance.get("is_active"):
        return None
    start = parse_iso(performance.get("time"), assume=timezone.utc)
    if start is None:
        log.debug("poravkino: performance %s has no usable time, skipped", performance.get("id"))
        return None
    title = text_or_none(movie.get("name")) or text_or_none(movie.get("ticket_name"))
    if title is None:
        log.debug("poravkino: performance %s belongs to a movie without a name, skipped", performance.get("id"))
        return None
    hall = text_or_none(performance.get("hall_name"))
    performance_id = performance.get("id")
    source_id = str(performance_id) if performance_id not in (None, "") else synthetic_id(ID, start, title, hall)
    price = to_int(performance.get("price"))
    tags = ("3D",) if performance.get("is3d") else ()
    return Screening(
        venue=ID,
        source_id=source_id,
        title=title,
        start=start,
        hall=hall,
        price_min=price,
        price_max=price,
        language=None,
        tags=tags,
        url=config.PORAVKINO_SITE_URL,
        source_url=source_url,
        extra=_extra(movie),
    )


def _extra(movie: dict) -> dict:
    extra: dict = {}
    year = to_int(movie.get("year"))
    if year is not None:
        extra["year"] = year
    for key, source_key in (("country", "country"), ("director", "director"), ("original_title", "name_secondary")):
        value = text_or_none(movie.get(source_key))
        if value:
            extra[key] = value
    duration = to_int(movie.get("duration"))
    if duration is not None:
        extra["duration_min"] = duration
    age = movie.get("age")
    if age not in (None, ""):
        extra["age"] = age
    genres = _genres(movie.get("genres"))
    if genres:
        extra["genres"] = genres
    if movie.get("is_pushkin") is not None:
        extra["is_pushkin"] = bool(movie.get("is_pushkin"))
    return extra


def _genres(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []
