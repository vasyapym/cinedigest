"""Аврора (avrora.spb.ru): Kinoplan kinokassa playbill API, site shell + one request per window day."""
from __future__ import annotations

import logging
import re
from datetime import date

from .. import config
from ..model import VENUES, Screening
from . import kinokassa, load_json

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
    out: list[Screening] = []
    for label, body in raw:
        if label == SHELL_LABEL:
            continue
        data = load_json(body, label, ID)
        source_url = (
            f"{playbill_url(config.AVRORA_API_FALLBACK)}?city_id={config.AVRORA_CITY_ID}&date={label}"
        )
        out.extend(
            kinokassa.parse_playbill(
                data,
                days,
                cinema_id=config.AVRORA_CINEMA_ID,
                venue=ID,
                url=config.AVRORA_SITE_URL,
                source_url=source_url,
                label=label,
            )
        )
    return kinokassa.dedupe_by_source_id(out)


def legit_empty(body: str) -> bool:
    """A valid playbill whose releases carry no seances at all (an ordinary empty day)."""
    return kinokassa.empty_playbill(body)
