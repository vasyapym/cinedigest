"""Ленфильм (lenfilm.ru) — полный суточный репертуар через kinokassa-фид KinoPlan.

The venue page embeds a KinoPlan kinowidget iframe (cinema 2387), so the adapter
speaks the kinokassa API directly and delegates every body to the shared parser:

1. bootstrap `GET /api/v2/app?with_cities=true&cinema_id=2387` — the site shell
   carries no token, and this account rejects the plain `X-Platform: widget`
   casing with HTTP 400 «Invalid headers», so one retry is sent with the casing
   verified for this account (`X-Platform: WIDGET`). The body carries the account
   application `token` (sent below as X-Application-Token) plus the sanity stamps
   `title` and `time_zone` (both only logged; only the token is required).
2. `GET /api/v2/release/playbill/info?cinema_id=2387` → the `calendar.seance_dates`
   list caps the day queries: playbills are fetched ONLY for window dates present
   in the list, window dates outside it are legit empty days (no request, no row).
3. `GET /api/v2/release/playbill?cinema_id=2387&date=YYYY-MM-DD` per covered date,
   parsed by the shared kinokassa module; every row links to the venue page
   (`url` = LENFILM_SITE_URL, per-seance purchase links are unverified).

The empty-window marker: when the info feed's `calendar.seance_dates` list exists
but intersects the requested window in zero days, fetch appends the synthetic pair
`("empty-window", '{"lenfilm_window_empty": true}')` to the raw set. `legit_empty`
returns True exactly for that marker body, so the pipeline's suspicious-zero rule
blesses the venue honestly — the marker documents WHY the window is empty (the
venue's own schedule never reached the window; compare the domkino schedule shell
or rodina's «Сеансы не найдены»). A missing/broken `calendar.seance_dates` list
is NOT blessed: fetch fails instead, because an unreadable schedule must not pass
as an empty one.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from .. import config
from ..http import HttpError
from ..model import VENUES, Screening
from . import kinokassa, load_json, text_or_none, to_int

log = logging.getLogger(__name__)

ID = "lenfilm"
NAME = VENUES[ID]
DAILY = True
APP_LABEL = "app"
INFO_LABEL = "info"
EMPTY_LABEL = "empty-window"
EMPTY_WINDOW_BODY = '{"lenfilm_window_empty": true}'


def app_url() -> str:
    return f"{config.KINOKASSA_API_URL}/api/v2/app"


def info_url() -> str:
    return f"{config.KINOKASSA_API_URL}/api/v2/release/playbill/info"


def playbill_url() -> str:
    return f"{config.KINOKASSA_API_URL}/api/v2/release/playbill"


def source_url(day_label: str) -> str:
    return f"{playbill_url()}?cinema_id={config.LENFILM_CINEMA_ID}&date={day_label}"


def app_credentials(data) -> tuple[str, str | None, int | None]:
    """(token, title, time_zone) of the account from the loaded bootstrap JSON.

    The token is required — nothing below it works without one, and lenfilm has no
    fallback constant. The title and time_zone are sanity stamps only; the frozen
    account carries time_zone inside cinemas[0], so it is read as a fallback from there.
    """
    token = None
    title = None
    time_zone = None
    cinemas = data.get("cinemas") if isinstance(data, dict) else None
    first_cinema = cinemas[0] if isinstance(cinemas, list) and cinemas and isinstance(cinemas[0], dict) else None
    if isinstance(data, dict):
        token = text_or_none(data.get("token"))
        title = text_or_none(data.get("title"))
        time_zone = to_int(data.get("time_zone"))
    if title is None and first_cinema is not None:
        title = text_or_none(first_cinema.get("title"))
    if time_zone is None and first_cinema is not None:
        time_zone = to_int(first_cinema.get("time_zone"))
    if token is None:
        raise ValueError(f"{ID} {APP_LABEL}: bootstrap response carries no 'token'")
    return token, title, time_zone


def seance_dates(info) -> list[date]:
    """`calendar.seance_dates` of the info feed as dates; ValueError when unreadable."""
    calendar = info.get("calendar") if isinstance(info, dict) else None
    items = calendar.get("seance_dates") if isinstance(calendar, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"{ID} {INFO_LABEL}: no 'calendar.seance_dates' list in the info feed")
    out = []
    for item in items:
        try:
            out.append(date.fromisoformat(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{ID} {INFO_LABEL}: unusable seance date {item!r}") from exc
    return out


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    raw: list[tuple[str, str]] = []
    app_body = _get(http, app_url(), params={"with_cities": "true", "cinema_id": config.LENFILM_CINEMA_ID}, label=APP_LABEL)
    raw.append((APP_LABEL, app_body))
    token, title, time_zone = app_credentials(load_json(app_body, APP_LABEL, ID))
    log.info("lenfilm: app feed %s (time_zone=%s)", title, time_zone)

    info_body = _get(http, info_url(), params={"cinema_id": config.LENFILM_CINEMA_ID}, token=token, label=INFO_LABEL)
    raw.append((INFO_LABEL, info_body))
    scheduled = set(seance_dates(load_json(info_body, INFO_LABEL, ID)))
    requested = [day for day in days if day in scheduled]
    log.info(
        "lenfilm: %d of %d scheduled seance dates fall inside the window %s..%s",
        len(requested), len(scheduled), days[0], days[-1],
    )
    for day in requested:
        label = day.isoformat()
        body = _get(
            http,
            playbill_url(),
            params={"cinema_id": config.LENFILM_CINEMA_ID, "date": label},
            token=token,
            label=label,
        )
        raw.append((label, body))
    if not requested:
        raw.append((EMPTY_LABEL, EMPTY_WINDOW_BODY))
        log.info("lenfilm: window %s..%s has no scheduled seance dates, empty-window marker recorded", days[0], days[-1])
    return raw


def parse(raw: list[tuple[str, str]], days: list[date]) -> list[Screening]:
    """Screenings of every day-playbill body; the `app`/`info`/marker bodies are skipped."""
    out: list[Screening] = []
    for label, body in raw:
        if label in (APP_LABEL, INFO_LABEL, EMPTY_LABEL):
            continue
        data = load_json(body, label, ID)
        out.extend(
            kinokassa.parse_playbill(
                data,
                days,
                cinema_id=config.LENFILM_CINEMA_ID,
                venue=ID,
                url=config.LENFILM_SITE_URL,
                source_url=source_url(label),
                label=label,
            )
        )
    return kinokassa.dedupe_by_source_id(out)


def legit_empty(body: str) -> bool:
    """True exactly for the synthetic empty-window marker (`fetch`'s own record of a
    window whose every day is outside the venue's scheduled seance dates)."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and data.get("lenfilm_window_empty") is True


def _get(http, url: str, *, params: dict, token: str | None = None, label: str) -> str:
    """GET with `X-Platform: widget`; on HTTP 400 («Invalid headers») one retry with
    the casing verified for this account (`X-Platform: WIDGET`)."""
    headers: dict[str, str] = {"X-Platform": "widget"}
    if token:
        headers["X-Application-Token"] = token
    try:
        return http.get(url, params=params, headers=headers, venue=ID, label=label)
    except HttpError as exc:
        if exc.status != 400:
            raise
        log.info("lenfilm: %s answered HTTP 400 («Invalid headers»), retrying with X-Platform: WIDGET", label)
        # fresh dict, so no caller ever observes the first request's headers changed
        return http.get(url, params=params, headers={**headers, "X-Platform": "WIDGET"}, venue=ID, label=label)
