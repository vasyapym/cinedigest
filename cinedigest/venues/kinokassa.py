"""Kinokassa playbill client, shared by the KinoPlan-kinokassa venues (avrora, lenfilm).

Parsing only: the releases→seances walk, the `cinema_id` equality filter, kopeck→ruble
prices, hall title, language wording (seance subtitles/voiceover first, then release
level), non-2D format tags, release metadata, the MSK day filter and the cross-body
dedupe by source id. No HTTP lives here — the venue adapters own fetching.
"""
from __future__ import annotations

import json
import logging

from ..model import MSK, Screening, synthetic_id
from . import parse_iso, text_or_none, to_int

log = logging.getLogger(__name__)


def parse_playbill(
    data,
    days,
    *,
    cinema_id: int,
    venue: str,
    url: str,
    source_url: str = "",
    label: str = "",
) -> list[Screening]:
    """Screenings of ONE playbill body (the already-loaded JSON dict).

    Raises ValueError when the body carries no 'releases' list — a structural surprise,
    the same failure the standalone adapters raised. Screenings outside the requested
    MSK calendar days are dropped; the caller dedupes across bodies and owns the
    source_url of the request the body was fetched with.
    """
    if not isinstance(data, dict) or not isinstance(data.get("releases"), list):
        raise ValueError(f"{venue} {label}: playbill without a 'releases' list")
    wanted = set(days)
    genres = lookup(data.get("genres"))
    countries = lookup(data.get("countries"))
    qualifiers = lookup(data.get("qualifiers"))
    qualifiers.update(lookup(data.get("all_qualifiers")))
    out: list[Screening] = []
    for release in data["releases"]:
        if not isinstance(release, dict):
            continue
        seances = release.get("seances")
        if not isinstance(seances, list):
            continue
        release_genres = resolve_all(release.get("genres"), genres)
        release_country = ", ".join(resolve_all(release.get("countries"), countries)) or None
        for seance in seances:
            if not isinstance(seance, dict):
                continue
            screening = _screening(
                release,
                seance,
                release_genres,
                release_country,
                qualifiers,
                cinema_id=cinema_id,
                venue=venue,
                url=url,
                source_url=source_url,
            )
            if screening is not None and screening.day in wanted:
                out.append(screening)
    return out


def dedupe_by_source_id(screenings: list[Screening]) -> list[Screening]:
    """First occurrence wins; the raw set may repeat a seance id across day labels."""
    seen: set[str] = set()
    out: list[Screening] = []
    for screening in screenings:
        if screening.source_id in seen:
            continue
        seen.add(screening.source_id)
        out.append(screening)
    return out


def empty_playbill(body: str) -> bool:
    """A valid playbill whose releases carry no seances at all (an ordinary empty day)."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    releases = data.get("releases")
    if not isinstance(releases, list):
        return False
    for release in releases:
        if not isinstance(release, dict):
            return False
        seances = release.get("seances")
        if not isinstance(seances, list) or seances:
            return False
    return True


def _screening(
    release: dict,
    seance: dict,
    release_genres: list[str],
    release_country: str | None,
    qualifiers: dict[str, str],
    *,
    cinema_id: int,
    venue: str,
    url: str,
    source_url: str,
) -> Screening | None:
    seance_cinema_id = to_int(seance.get("cinema_id"))
    if seance_cinema_id is not None and seance_cinema_id != cinema_id:
        return None
    start = parse_iso(seance.get("start_date_time"), assume=MSK)
    if start is None:
        log.debug("%s: seance %s has no usable start_date_time, skipped", venue, seance.get("id"))
        return None
    title = text_or_none(release.get("title"))
    if title is None:
        log.debug("%s: seance %s belongs to a release without a title, skipped", venue, seance.get("id"))
        return None
    hall = _hall(seance.get("hall"))
    seance_id = seance.get("id")
    source_id = str(seance_id) if seance_id not in (None, "") else synthetic_id(venue, start, title, hall)
    price_min, price_max = _prices(seance.get("price"))
    extra: dict = {}
    if release.get("id") is not None:
        extra["release_id"] = release.get("id")
    year = to_int(release.get("year"))
    if year is not None:
        extra["year"] = year
    duration = to_int(release.get("duration"))
    if duration is not None:
        extra["duration_min"] = duration
    age = release.get("age_rating")
    if age not in (None, ""):
        extra["age"] = age
    if release_genres:
        extra["genres"] = list(release_genres)
    if release_country:
        extra["country"] = release_country
    free_places = to_int(seance.get("free_places_count"))
    if free_places is not None:
        extra["free_places"] = free_places
    if isinstance(seance.get("is_allowed_online_sale"), bool):
        extra["online_sale"] = seance["is_allowed_online_sale"]
    return Screening(
        venue=venue,
        source_id=source_id,
        title=title,
        start=start,
        hall=hall,
        price_min=price_min,
        price_max=price_max,
        language=_language(release, seance, qualifiers),
        tags=_tags(seance),
        url=url,
        source_url=source_url,
        extra=extra,
    )


def _hall(value) -> str | None:
    if isinstance(value, dict):
        return text_or_none(value.get("title") or value.get("name"))
    return text_or_none(value)


def _kopecks_to_rubles(value) -> int | None:
    kopecks = to_int(value)
    return None if kopecks is None else kopecks // 100


def _prices(price) -> tuple[int | None, int | None]:
    if isinstance(price, dict):
        low = _kopecks_to_rubles(price.get("min"))
        high = _kopecks_to_rubles(price.get("max"))
    else:
        low = high = _kopecks_to_rubles(price)
    if low is None:
        low = high
    if high is None:
        high = low
    return low, high


def _tags(seance: dict) -> tuple[str, ...]:
    tags: list[str] = []
    formats = seance.get("formats")
    if isinstance(formats, list):
        for fmt in formats:
            title = text_or_none(fmt.get("title")) if isinstance(fmt, dict) else text_or_none(fmt)
            if title and title.upper() != "2D" and title not in tags:
                tags.append(title)
    return tuple(tags)


def _language(release: dict, seance: dict, qualifiers: dict[str, str]) -> str | None:
    if seance.get("subtitles"):
        return "SUB"
    voice = wording(seance.get("voiceover"), qualifiers)
    if voice:
        return voice
    if release.get("subtitles"):
        return "SUB"
    voices = resolve_all(release.get("voiceovers"), qualifiers)
    return ", ".join(voices) or None


def wording(value, table: dict[str, str]) -> str | None:
    """Language wording of one subtitles/voiceover value against the qualifier table."""
    if value is None or value is False:
        return None
    if isinstance(value, dict):
        return text_or_none(value.get("title") or value.get("name"))
    if isinstance(value, str):
        return text_or_none(value)
    if isinstance(value, (int, float)):
        return table.get(str(value))
    return None


def lookup(items) -> dict[str, str]:
    """id → title table from the playbill lookup lists."""
    table: dict[str, str] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                key = item.get("id")
                title = text_or_none(item.get("title") or item.get("name"))
                if key is not None and title:
                    table[str(key)] = title
    return table


def resolve_all(value, table: dict[str, str]) -> list[str]:
    """Resolve a release-level list of ids (or already-shaped dicts) against the table."""
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                title = text_or_none(item.get("title") or item.get("name"))
                if title:
                    out.append(title)
            elif item is not None:
                title = table.get(str(item))
                if title:
                    out.append(title)
    return out
