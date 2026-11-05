"""Дом кино (domkino.spb.ru): server-rendered schedule pages, one request per window day."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .. import config
from ..model import MSK, VENUES, Screening, synthetic_id

log = logging.getLogger(__name__)

ID = "domkino"
NAME = VENUES[ID]
DAILY = True

# Hall headings on a day page: <h3>Большой зал</h3> etc. — exact stripped text.
HALLS = ("Большой зал", "Синий зал", "Белый зал", "Сиреневый зал", "Малый зал")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_FILMS_RE = re.compile(r"^/films/")


def day_url(day: date) -> str:
    return f"{config.DOMKINO_SITE_URL}schedule/{day.strftime('%Y/%m/%d')}/"


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    raw: list[tuple[str, str]] = []
    for day in days:
        label = day.isoformat()
        body = http.get(day_url(day), venue=ID, label=label)
        raw.append((label, body))
    return raw


def parse(raw: list[tuple[str, str]], days: list[date]) -> list[Screening]:
    """Schedule tables of each hall on every day page; times are local MSK of the page date.

    The page interleaves the row tables with film-card blocks between them, so rows
    are taken table by table starting from each hall heading. A far-future day returns
    a schedule shell without hall headings and yields nothing (a legitimate empty day).
    """
    wanted = set(days)
    seen: set[str] = set()
    out: list[Screening] = []
    for label, body in raw:
        day = _label_date(label)
        if day is None:
            log.debug("domkino: label %r is not an ISO date, body skipped", label)
            continue
        source_url = day_url(day)
        for screening in _page_screenings(body, day, source_url):
            if screening.day not in wanted or screening.source_id in seen:
                continue
            seen.add(screening.source_id)
            out.append(screening)
    return out


def legit_empty(body: str) -> bool:
    """True iff the body is a schedule page without any of the five hall headings.

    That shell (HTTP 200, no error, no sessions) is the venue's own empty-day shape.
    «Расписание» must also be present: it is the title/heading of every schedule page,
    so an unrelated 200-shell would not be blessed as a legitimate empty day.
    """
    try:
        soup = _soup(body)
    except Exception as exc:
        log.debug("domkino: legit_empty could not parse the body (%s)", exc)
        return False
    if _hall_headings(soup):
        return False
    return "Расписание" in body


def _page_screenings(body: str, day: date, source_url: str) -> list[Screening]:
    soup = _soup(body)
    out: list[Screening] = []
    for heading in _hall_headings(soup):
        hall = heading.get_text(strip=True)
        for table in _section_tables(heading):
            out.extend(_table_screenings(table, day, source_url, hall))
    return out


def _label_date(label: str) -> date | None:
    try:
        return date.fromisoformat(label)
    except ValueError:
        return None


def _soup(body: str) -> BeautifulSoup:
    return BeautifulSoup(body, "lxml")


def _hall_headings(soup) -> list[Tag]:
    return [
        heading
        for heading in soup.find_all(_HEADINGS)
        if heading.get_text(strip=True) in HALLS
    ]


def _section_tables(heading: Tag) -> list[Tag]:
    """Tables of one hall section: from its heading up to (but not including) the
    next hall heading. Without this bound every heading would claim all later halls'
    tables too."""
    tables: list[Tag] = []
    for node in heading.find_all_next(_HEADINGS + ("table",)):
        if node.name != "table":
            if node.get_text(strip=True) in HALLS:
                break
            continue
        tables.append(node)
    return tables


def _table_screenings(table: Tag, day: date, source_url: str, hall: str) -> list[Screening]:
    out: list[Screening] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells or not _TIME_RE.match(cells[0].get_text(strip=True)):
            continue
        if len(cells) != 5:
            log.debug("domkino %s: row %s has %d cells, expected 5, skipped",
                      hall, cells[0].get_text(strip=True), len(cells))
            continue
        screening = _screening(cells, day, source_url, hall)
        if screening is None:
            continue
        out.append(screening)
    return out


def _screening(cells: list[Tag], day: date, source_url: str, hall: str) -> Screening | None:
    hours, minutes = (int(part) for part in cells[0].get_text(strip=True).split(":"))
    try:
        start = datetime.combine(day, time(hours, minutes), tzinfo=MSK)
    except ValueError as exc:
        log.debug("domkino %s: unusable time (%s), skipped", hall, exc)
        return None
    title = cells[1].get_text(" ", strip=True)
    if not title:
        log.debug("domkino %s %s: row without a film title, skipped", hall, cells[0])
        return None
    genres = [
        part.strip()
        for part in cells[2].get_text(" ", strip=True).split(",")
        if part.strip()
    ]
    language = cells[3].get_text(" ", strip=True) or None
    price = _price(cells[4])
    film_url = _film_url(cells[1])
    extra: dict = {}
    if genres:
        extra["genres"] = genres
    return Screening(
        venue=ID,
        source_id=synthetic_id(ID, start, title, hall),
        title=title,
        start=start,
        hall=hall,
        price_min=price,
        price_max=price,
        language=language,
        tags=(),
        url=film_url,
        source_url=source_url,
        extra=extra,
    )


def _price(cell: Tag) -> int | None:
    """Первое число в цене: «400 руб.» → 400, «350/200» → 350 (основной взрослый билет)."""
    match = re.search(r"\d+", cell.get_text(" ", strip=True))
    return int(match.group()) if match else None


def _film_url(title_cell: Tag) -> str | None:
    """The film page link of one row: /films/<slug>/ anchor inside the title cell or,
    as in the real markup, inside the film-card block right after the row's table
    (the walk stops at the next <table> so it cannot reach another row's card)."""
    anchor = title_cell.find("a", href=_FILMS_RE)
    if anchor is not None:
        return urljoin(config.DOMKINO_SITE_URL, anchor.get("href", ""))
    table = title_cell.find_parent("table")
    if table is None:
        return None
    for element in table.next_elements:
        if element is table:
            continue
        name = getattr(element, "name", None)
        if name == "table":
            return None
        if name == "a" and _FILMS_RE.match(element.get("href", "")):
            return urljoin(config.DOMKINO_SITE_URL, element["href"])
    return None
