"""Родина (rodinakino.ru): server-rendered page of platform p24.app, one request per window day."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .. import config
from ..model import MSK, VENUES, Screening, synthetic_id

log = logging.getLogger(__name__)

ID = "rodina"
NAME = VENUES[ID]
DAILY = True

# The venue's empty-day marker («Сеансы не найдены»). The same phrase also sits in
# every page's embedded i18n dictionary <script>, so the check must look at rendered
# text only (scripts and styles are cut off before the search).
EMPTY_MARKER = "Сеансы не найдены"

# Show-time anchors carry their full date+time as a URL fragment
# (?date=...&facility=...#YYYY/MM/DD HH:MM, the space may be percent-encoded).
_FRAGMENT_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})$")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_EVENTS_RE = re.compile(r"/events/")
_SHOW_BOX_RE = re.compile(r"^Show_show__")


def day_url(day: date) -> str:
    return f"{config.RODINA_SITE_URL}?date={day.strftime('%Y/%m/%d')}"


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    raw: list[tuple[str, str]] = []
    for day in days:
        label = day.isoformat()
        body = http.get(day_url(day), venue=ID, label=label)
        raw.append((label, body))
    return raw


def parse(raw: list[tuple[str, str]], days: list[date]) -> list[Screening]:
    """Every show-time anchor of the page, with the fragment as the truth about the start.

    The fragment dates may differ from the requested day (the platform also renders
    the nearest shows of neighbouring days on a day page), so screenings are NOT cut
    by `days` here — `days` is kept for the adapter contract; the pipeline applies the
    window itself. The `facility` parameter was validated as not required, so pages
    fetched without it parse the same.
    """
    seen: set[str] = set()
    out: list[Screening] = []
    for label, body in raw:
        source_url = _source_url(label)
        for screening in _page_screenings(body, source_url):
            if screening.source_id in seen:
                continue
            seen.add(screening.source_id)
            out.append(screening)
    return out


def legit_empty(body: str) -> bool:
    """True iff «Сеансы не найдены» is rendered somewhere in the body.

    The phrase is also part of the i18n dictionary embedded as a <script> on EVERY
    page (including days full of sessions), so <script> and <style> content is
    removed before the search.
    """
    try:
        soup = BeautifulSoup(body, "lxml")
    except Exception as exc:
        log.debug("rodina: legit_empty could not parse the body (%s)", exc)
        return False
    for hidden in soup.find_all(("script", "style", "noscript")):
        hidden.decompose()
    return EMPTY_MARKER in soup.get_text(" ")


def _source_url(label: str) -> str:
    day = _label_date(label)
    if day is not None:
        return day_url(day)
    log.debug("rodina: label %r is not an ISO date; using the venue root as source", label)
    return config.RODINA_SITE_URL


def _label_date(label: str) -> date | None:
    try:
        return date.fromisoformat(label)
    except ValueError:
        return None


def _page_screenings(body: str, source_url: str) -> list[Screening]:
    soup = BeautifulSoup(body, "lxml")
    out: list[Screening] = []
    for anchor in soup.find_all("a", href=True):
        fragment = unquote(anchor["href"].partition("#")[2])
        match = _FRAGMENT_RE.match(fragment)
        if not match:
            continue
        screening = _screening(anchor, match, source_url)
        if screening is not None:
            out.append(screening)
    return out


def _screening(anchor: Tag, match: re.Match, source_url: str) -> Screening | None:
    year, month, day, hour, minute = (int(part) for part in match.groups())
    try:
        start = datetime(year, month, day, hour, minute, tzinfo=MSK)
    except ValueError as exc:
        log.debug("rodina: unusable fragment date (%s), skipped", exc)
        return None
    show = _show_box(anchor)
    block, title = _event_block(anchor)
    if title is None:
        log.debug("rodina: anchor %r has no enclosing event block with a heading, skipped", anchor.get("href"))
        return None
    price = _price(show)
    return Screening(
        venue=ID,
        source_id=synthetic_id(ID, start, title, None),
        title=title,
        start=start,
        hall=None,
        price_min=price,
        price_max=price,
        language=_language(show),
        tags=(),
        url=_event_url(block),
        source_url=source_url,
        extra={},
    )


def _show_box(anchor: Tag) -> Tag | None:
    """The Show_show__* block owning the anchor: its price and SUB badge live inside."""
    node = anchor.find_parent("div")
    while node is not None:
        classes = node.get("class") or []
        if any(_SHOW_BOX_RE.match(token) for token in classes):
            return node
        node = node.find_parent("div")
    return None


def _event_block(anchor: Tag) -> tuple[Tag | None, str | None]:
    """(enclosing block, title): climb to the nearest ancestor that carries a heading
    and take its first heading text (in document order). The same block is searched
    for the event link."""
    node = anchor
    while node is not None:
        node = node.parent
        if node is None:
            break
        heading = node.find(_HEADINGS, recursive=True)
        if heading is not None:
            text = heading.get_text(" ", strip=True)
            return node, text or None
    return None, None


def _event_url(block: Tag | None) -> str | None:
    """The /events/<slug> link of the event block, if the block carries one (it does
    for the schedule list; the gallery-slider shows have none — then None)."""
    if block is None:
        return None
    link = block.find("a", href=_EVENTS_RE)
    if link is None:
        return None
    path = urlsplit(link.get("href", "")).path
    if not path:
        return None
    return urljoin(config.RODINA_SITE_URL, path)


def _price(show: Tag | None) -> int | None:
    """Price of one show when the block renders it («250 ₽» with a thin space); None
    when the block has no price line (gallery-slider badge shows)."""
    if show is None:
        return None
    for price in show.find_all("div"):
        classes = price.get("class") or []
        if not any(str(token).startswith("Show_price__") for token in classes):
            continue
        match = re.search(r"\d+", price.get_text(" ", strip=True))
        return int(match.group()) if match else None
    return None


def _language(show: Tag | None) -> str | None:
    """'SUB' when the show block itself is marked SUB (class or data-format badge)."""
    if show is None:
        return None
    if "SUB" in (show.get("class") or []):
        return "SUB"
    if show.find("span", attrs={"data-format": "SUB"}):
        return "SUB"
    return None
