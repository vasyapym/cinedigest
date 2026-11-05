"""Аврора (avrora.spb.ru): Kinoplan kinokassa playbill API, site shell + one request per window day."""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from .. import config
from ..model import MSK, VENUES, Screening, synthetic_id
from . import load_json, parse_iso, text_or_none, to_int

log = logging.getLogger(__name__)

ID = "avrora"
NAME = VENUES[ID]
DAILY = True
SHELL_LABEL = "shell"
API_URL_RE = re.compile(r'kinokassaApiUrl="([^"]+)"')
TOKEN_RE = re.compile(r'kinositeSettings=\{token:"([A-Za-z0-9]+)"')


def resolve_settings(shell: str) -> tuple[str, str]:
    """(api base, token) from the site shell; constants when the shell does not expose them."""
    api = config.AVRORA_API_FALLBACK
    token = config.AVRORA_TOKEN_FALLBACK
    if shell:
        match = API_URL_RE.search(shell)
        if match:
            candidate = match.group(1).replace("\\/", "/").strip().rstrip("/")
            if candidate.startswith("http"):
                api = candidate
        match = TOKEN_RE.search(shell)
        if match:
            token = match.group(1)
    return api, token


def playbill_url(api_base: str) -> str:
    return f"{api_base.rstrip('/')}/api/v2/release/playbill"


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    raw: list[tuple[str, str]] = []
    shell = ""
    try:
        shell = http.get(config.AVRORA_SITE_URL, venue=ID, label=SHELL_LABEL)
    except Exception as exc:
        log.warning("avrora: site shell unavailable (%s); using fallback API settings", exc)
    else:
        raw.append((SHELL_LABEL, shell))
    api, token = resolve_settings(shell)
    headers = {"X-Application-Token": token, "X-Platform": "widget"}
    for day in days:
        label = day.isoformat()
        body = http.get(
            playbill_url(api),
            params={"city_id": config.AVRORA_CITY_ID, "date": label},
            headers=headers,
            venue=ID,
            label=label,
        )
        raw.append((label, body))
    return raw


def parse(raw: list[tuple[str, str]], days: list[date]) -> list[Screening]:
    wanted = set(days)
    seen: set[str] = set()
    out: list[Screening] = []
    for label, body in raw:
        if label == SHELL_LABEL:
            continue
        data = load_json(body, label, ID)
        if not isinstance(data, dict) or not isinstance(data.get("releases"), list):
            raise ValueError(f"{ID} {label}: playbill without a 'releases' list")
        genres = _lookup(data.get("genres"))
        countries = _lookup(data.get("countries"))
        qualifiers = _lookup(data.get("qualifiers"))
        qualifiers.update(_lookup(data.get("all_qualifiers")))
        source_url = (
            f"{playbill_url(config.AVRORA_API_FALLBACK)}?city_id={config.AVRORA_CITY_ID}&date={label}"
        )
        for release in data["releases"]:
            if not isinstance(release, dict):
                continue
            seances = release.get("seances")
            if not isinstance(seances, list):
                continue
            release_genres = _resolve_all(release.get("genres"), genres)
            release_country = ", ".join(_resolve_all(release.get("countries"), countries)) or None
            for seance in seances:
                if not isinstance(seance, dict):
                    continue
                screening = _screening(release, seance, release_genres, release_country, qualifiers, source_url)
                if screening is None or screening.day not in wanted or screening.source_id in seen:
                    continue
                seen.add(screening.source_id)
                out.append(screening)
    return out


def legit_empty(body: str) -> bool:
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
    source_url: str,
) -> Screening | None:
    cinema_id = to_int(seance.get("cinema_id"))
    if cinema_id is not None and cinema_id != config.AVRORA_CINEMA_ID:
        return None
    start = parse_iso(seance.get("start_date_time"), assume=MSK)
    if start is None:
        log.debug("avrora: seance %s has no usable start_date_time, skipped", seance.get("id"))
        return None
    title = text_or_none(release.get("title"))
    if title is None:
        log.debug("avrora: seance %s belongs to a release without a title, skipped", seance.get("id"))
        return None
    hall = _hall(seance.get("hall"))
    seance_id = seance.get("id")
    source_id = str(seance_id) if seance_id not in (None, "") else synthetic_id(ID, start, title, hall)
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
        venue=ID,
        source_id=source_id,
        title=title,
        start=start,
        hall=hall,
        price_min=price_min,
        price_max=price_max,
        language=_language(release, seance, qualifiers),
        tags=_tags(seance),
        url=config.AVRORA_SITE_URL,
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
    voice = _wording(seance.get("voiceover"), qualifiers)
    if voice:
        return voice
    if release.get("subtitles"):
        return "SUB"
    voices = _resolve_all(release.get("voiceovers"), qualifiers)
    return ", ".join(voices) or None


def _wording(value, table: dict[str, str]) -> str | None:
    if value is None or value is False:
        return None
    if isinstance(value, dict):
        return text_or_none(value.get("title") or value.get("name"))
    if isinstance(value, str):
        return text_or_none(value)
    if isinstance(value, (int, float)):
        return table.get(str(value))
    return None


def _lookup(items) -> dict[str, str]:
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


def _resolve_all(value, table: dict[str, str]) -> list[str]:
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
