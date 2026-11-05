"""Дом кино (domkino.spb.ru): server-rendered schedule pages, one request per window day."""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
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

# Film-card line «2026 / Россия / комедия[ / дублированный]»: the year first, then the
# country segment (capitalised), the genres (lowercase), sometimes the translation wording.
_YEAR_LINE_RE = re.compile(r"^\s*(1[89]\d{2}|20\d{2})\s*/\s*(.*)$", re.DOTALL)
_DURATION_RE = re.compile(r"(\d+)\s*мин")
_DIRECTOR_RE = re.compile(r"^Режисс[её]р[ыа]?\s*:\s*(.+)$", re.DOTALL)


@dataclass(frozen=True)
class FilmCard:
    """What the film-card block after a row table says about the table's film."""

    url: str | None = None
    year: int | None = None
    country: str | None = None
    duration_min: int | None = None
    age: str | None = None
    original_title: str | None = None
    director: str | None = None

    def facts(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != "url" and value is not None}


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
    are taken table by table starting from each hall heading, and each table's card
    (year, country, duration, age, original title, director, film link) is attached
    to its rows. A far-future day returns a schedule shell without hall headings and
    yields nothing (a legitimate empty day).
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
    card = _film_card(table)
    out: list[Screening] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells or not _TIME_RE.match(cells[0].get_text(strip=True)):
            continue
        if len(cells) != 5:
            log.debug("domkino %s: row %s has %d cells, expected 5, skipped",
                      hall, cells[0].get_text(strip=True), len(cells))
            continue
        screening = _screening(cells, day, source_url, hall, card)
        if screening is None:
            continue
        out.append(screening)
    return out


def _screening(cells: list[Tag], day: date, source_url: str, hall: str, card: FilmCard) -> Screening | None:
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
    extra: dict = card.facts()
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
        url=_film_url(cells[1]) or card.url,
        source_url=source_url,
        extra=extra,
    )


def _price(cell: Tag) -> int | None:
    """Первое число в цене: «400 руб.» → 400, «350/200» → 350 (основной взрослый билет)."""
    match = re.search(r"\d+", cell.get_text(" ", strip=True))
    return int(match.group()) if match else None


def _film_url(title_cell: Tag) -> str | None:
    """A /films/<slug>/ anchor inside the title cell itself (not the real markup today,
    kept as the first choice); otherwise the card's link is used."""
    anchor = title_cell.find("a", href=_FILMS_RE)
    if anchor is None:
        return None
    return urljoin(config.DOMKINO_SITE_URL, anchor.get("href", ""))


def _film_card(table: Tag) -> FilmCard:
    """The film-card block right after one row table: poster/«Подробнее» link, «2026 /
    Россия / комедия», duration and age spans, original title, «Режиссёр: …». The walk
    stops at the next <table> or hall heading, so a card can never be read for another
    table's rows; the table's own cells are skipped."""
    url = year = country = duration = age = original = director = None
    for element in table.next_elements:
        if not isinstance(element, Tag) or element is table or element.find_parent("table") is table:
            continue
        name = element.name
        if name == "table" or (name in _HEADINGS and element.get_text(strip=True) in HALLS):
            break
        classes = element.get("class") or []
        if name == "a" and url is None and _FILMS_RE.match(element.get("href", "")):
            url = urljoin(config.DOMKINO_SITE_URL, element["href"])
        elif name == "p":
            text = " ".join(element.get_text(" ", strip=True).split())
            line = _YEAR_LINE_RE.match(text)
            if line is not None and year is None:
                year = int(line.group(1))
                country = _country(line.group(2))
                continue
            who = _DIRECTOR_RE.match(text)
            if who is not None and director is None:
                director = who.group(1).strip() or None
        elif name == "span" and "duration" in classes and duration is None:
            match = _DURATION_RE.search(element.get_text(" ", strip=True))
            duration = int(match.group(1)) if match else None
        elif name == "span" and "vozrast" in classes and age is None:
            age = element.get_text(strip=True) or None
        elif name == "h3" and "en_name" in classes and original is None:
            original = element.get_text(" ", strip=True) or None
    return FilmCard(url, year, country, duration, age, original, director)


def _country(rest: str) -> str | None:
    """The capitalised segment after the year («Россия», «США, Великобритания»); genres
    are lowercase and the translation wording comes last."""
    for segment in (part.strip() for part in rest.split("/")):
        if segment and segment[0].isupper():
            return segment
    return None
