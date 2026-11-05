"""Мираж на Большом (www.mirage.ru): the city-wide per-day schedule page of the chain,
cut to the block of branch 1 («НА БОЛЬШОМ», Большой пр. П.С., 35А). One request per window day."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .. import config
from ..model import MSK, VENUES, Screening, synthetic_id

log = logging.getLogger(__name__)

ID = "mirage"
NAME = VENUES[ID]
DAILY = True

_BRANCH_HREF_RE = re.compile(r"/spb/cinema/(\d+)/")
_TICKET_RE = re.compile(r"/ticket_new/([0-9a-fA-F-]{8,})/?")
_DATE_TAB_RE = re.compile(r"/spb/schedule/(\d{2})\.(\d{2})\.(\d{4})/")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_HALL_RE = re.compile(r"^зал\s*№?\s*(\d+)$", re.IGNORECASE)
_FILM_ID_RE = re.compile(r"/p(\d+)\.[a-z]+$", re.IGNORECASE)

# Formats that carry no information for the owner; anything else («3D», «IMAX») is a tag.
_PLAIN_FORMATS = {"2D"}


def day_url(day: date) -> str:
    return f"{config.MIRAGE_SITE_URL}spb/schedule/{day.strftime('%d.%m.%Y')}/"


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    raw: list[tuple[str, str]] = []
    for day in days:
        label = day.isoformat()
        body = http.get(day_url(day), venue=ID, label=label)
        raw.append((label, body))
    return raw


def parse(raw: list[tuple[str, str]], days: list[date]) -> list[Screening]:
    """Seances of the wanted branch on every day page; times are local MSK of the page date.

    A page whose active date tab names another date (the site publishes about five
    day tabs; what a later date serves is not verified) is skipped entirely so that
    no row can be filed under a wrong day. Other branches never produce rows.
    """
    wanted = set(days)
    seen: set[str] = set()
    out: list[Screening] = []
    for label, body in raw:
        day = _label_date(label)
        if day is None:
            log.debug("mirage: label %r is not an ISO date, body skipped", label)
            continue
        soup = _soup(body)
        active = _active_tab_date(soup)
        if active is not None and active != day:
            log.warning("mirage: page requested for %s renders %s, skipped", day, active)
            continue
        box = _branch_box(soup)
        if box is None:
            continue
        for screening in _box_screenings(box, day, day_url(day)):
            if screening.day not in wanted or screening.source_id in seen:
                continue
            seen.add(screening.source_id)
            out.append(screening)
    return out


def legit_empty(body: str) -> bool:
    """The venue's own «nothing for our branch» shapes:

    * a schedule page whose branch blocks all carry their /spb/cinema/N/ link, and
      where either our branch has no block at all or no branch has a single session
      (the day is not published yet);
    * a bare date-tab shell without any branch block.

    Our block present but empty while other branches do have sessions, or blocks
    that lost their links, are NOT blessed — that smells like a layout change and
    must stay suspicious.
    """
    try:
        soup = _soup(body)
    except Exception as exc:
        log.debug("mirage: legit_empty could not parse the body (%s)", exc)
        return False
    boxes = soup.select("div.session-box")
    if not boxes:
        return soup.find("a", href=_DATE_TAB_RE) is not None
    ids = [_branch_id(box) for box in boxes]
    if any(branch_id is None for branch_id in ids):
        return False
    if config.MIRAGE_BRANCH_ID not in ids:
        return True
    return not soup.select("div.session")


def warning(raw: list[tuple[str, str]]) -> str | None:
    """Days whose page rendered another date (beyond the published tabs) — shown as ⚠."""
    off: list[date] = []
    for label, body in raw:
        day = _label_date(label)
        if day is None:
            continue
        try:
            active = _active_tab_date(_soup(body))
        except Exception:
            continue
        if active is not None and active != day:
            off.append(day)
    if not off:
        return None
    listed = ", ".join(day.strftime("%d.%m") for day in off)
    return f"сайт отдал другую дату вместо {listed} — расписания на эти дни ещё нет"


def _label_date(label: str) -> date | None:
    try:
        return date.fromisoformat(label)
    except ValueError:
        return None


def _soup(body: str) -> BeautifulSoup:
    return BeautifulSoup(body, "lxml")


def _active_tab_date(soup) -> date | None:
    for anchor in soup.find_all("a", href=_DATE_TAB_RE):
        if "active" not in (anchor.get("class") or []):
            continue
        day, month, year = (int(part) for part in _DATE_TAB_RE.search(anchor["href"]).groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _branch_id(box: Tag) -> int | None:
    link = box.select_one(".md-title a[href]")
    if link is None:
        return None
    match = _BRANCH_HREF_RE.search(link.get("href", ""))
    return int(match.group(1)) if match else None


def _branch_box(soup) -> Tag | None:
    """The session-box of the wanted branch: by id from its title link, by name as a
    fallback; never by position."""
    boxes = soup.select("div.session-box")
    for box in boxes:
        if _branch_id(box) == config.MIRAGE_BRANCH_ID:
            return box
    for box in boxes:
        title = box.select_one(".md-title")
        if title is None:
            continue
        if " ".join(title.get_text(" ", strip=True).split()).upper() == config.MIRAGE_BRANCH_NAME:
            log.warning("mirage: branch found by name only — the title link pattern changed?")
            return box
    return None


def _box_screenings(box: Tag, day: date, source_url: str) -> list[Screening]:
    out: list[Screening] = []
    for session in box.select("div.session"):
        screening = _screening(session, day, source_url)
        if screening is not None:
            out.append(screening)
    return out


def _screening(session: Tag, day: date, source_url: str) -> Screening | None:
    title = _text(session.select_one(".title"))
    clock = _text(session.select_one(".info-line .time") or session.select_one(".time"))
    match = _TIME_RE.match(clock or "")
    if not title or match is None:
        log.debug("mirage: session without title/time skipped (%r, %r)", title, clock)
        return None
    try:
        start = datetime.combine(day, time(int(match.group(1)), int(match.group(2))), tzinfo=MSK)
    except ValueError as exc:
        log.debug("mirage: unusable time %r (%s), skipped", clock, exc)
        return None
    hall = _hall(session)
    anchor = session.find("a", href=_TICKET_RE)
    url = urljoin(config.MIRAGE_SITE_URL, anchor["href"]) if anchor is not None else None
    ticket = _TICKET_RE.search(anchor["href"]).group(1) if anchor is not None else None
    extra: dict = {}
    genres = [part.strip() for part in (_text(session.select_one(".genre")) or "").split(",") if part.strip()]
    if genres:
        extra["genres"] = genres
    age = _text(session.select_one(".age"))
    if age:
        extra["age"] = age
    price_raw = _text(session.select_one(".place-price"))
    if price_raw:
        extra["price_raw"] = price_raw  # «30000₽»: semantics unverified, kept for the follow-up
    film_id = _film_id(session)
    if film_id is not None:
        extra["film_id"] = film_id
    fmt = _text(session.select_one(".format"))
    tags = (fmt,) if fmt and fmt.upper() not in _PLAIN_FORMATS else ()
    return Screening(
        venue=ID,
        source_id=ticket or synthetic_id(ID, start, title, hall),
        title=title,
        start=start,
        hall=hall,
        price_min=None,
        price_max=None,
        language=None,
        tags=tags,
        url=url,
        source_url=source_url,
        extra=extra,
    )


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def _hall(session: Tag) -> str | None:
    """«Зал №2» → «2» (renders as «зал 2»); any other label naming a зал stays verbatim."""
    labels = session.select_one(".labels")
    if labels is None:
        return None
    for span in labels.find_all("span"):
        text = _text(span) or ""
        match = _HALL_RE.match(text)
        if match:
            return match.group(1)
        if "зал" in text.lower():
            return text
    return None


def _film_id(session: Tag) -> int | None:
    image = session.select_one(".photo img[src]")
    if image is None:
        return None
    match = _FILM_ID_RE.search(image.get("src", ""))
    return int(match.group(1)) if match else None
