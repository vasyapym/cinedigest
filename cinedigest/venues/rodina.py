"""Родина (rodinakino.ru): server-rendered pages of platform p24.app — one request per window day plus one best-effort request per distinct film of the window (its /events/<slug> page)."""
from __future__ import annotations

import logging
import re
from dataclasses import replace
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

# Raw labels: an ISO date for a day page, «event:<slug>» for a film page. An empty body
# under an event label means the film page could not be fetched: parse() then yields the
# screening without film facts and warning() reports the count.
EVENT_LABEL_PREFIX = "event:"

# Show-time anchors carry their full date+time as a URL fragment
# (?date=...&facility=...#YYYY/MM/DD HH:MM, the space may be percent-encoded).
_FRAGMENT_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})$")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_EVENTS_RE = re.compile(r"/events/")
_SHOW_BOX_RE = re.compile(r"^Show_show__")
_TAGS_RE = re.compile(r"^EventShowsList_tags__")

_YEAR_CHIP_RE = re.compile(r"^(1[89]\d{2}|20\d{2})$")
_AGE_CHIP_RE = re.compile(r"^\d{1,2}\+$")
_AGE_RE = re.compile(r"^\s*(\d{1,2})\s*\+?\s*$")
_MOVIE_RE = re.compile(r"schema\.org/Movie$")
_HOURS_RE = re.compile(r"(\d+)\s*час")
_MINUTES_RE = re.compile(r"(\d+)\s*мин")
_ISO_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?", re.IGNORECASE)
_SYNOPSIS_LIMIT = 320


def day_url(day: date) -> str:
    return f"{config.RODINA_SITE_URL}?date={day.strftime('%Y/%m/%d')}"


def event_url(slug: str) -> str:
    return urljoin(config.RODINA_SITE_URL, f"events/{slug}")


def slug_of(url: str | None) -> str | None:
    """«https://rodinakino.ru/events/idealnyj-shtorm-2026?facility=…» → «idealnyj-shtorm-2026»."""
    if not url:
        return None
    path = urlsplit(url).path
    marker = "/events/"
    if marker not in path:
        return None
    slug = path.split(marker, 1)[1].strip("/")
    return slug or None


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    """The day pages, then the film page of every distinct film shown inside the window.

    Film pages are best-effort: a page that cannot be fetched is recorded as an empty
    body under its «event:» label. After RODINA_EVENT_FAILURE_LIMIT failed film pages the
    remaining ones are not requested at all (recorded empty) — a slow day of
    rodinakino.ru must not multiply the retry budget by the number of films.
    """
    raw: list[tuple[str, str]] = []
    for day in days:
        label = day.isoformat()
        raw.append((label, http.get(day_url(day), venue=ID, label=label)))
    failures = 0
    for slug in event_slugs(raw, days):
        label = EVENT_LABEL_PREFIX + slug
        body = ""
        if failures < config.RODINA_EVENT_FAILURE_LIMIT:
            try:
                body = http.get(event_url(slug), venue=ID, label=label)
            except Exception as exc:  # the schedule is already in hand; film facts are optional
                failures += 1
                log.warning("rodina: film page %s not fetched (%s)", slug, exc)
        raw.append((label, body))
    return raw


def event_slugs(raw: list[tuple[str, str]], days: list[date]) -> list[str]:
    """Distinct film slugs of the screenings inside `days`, in document order, capped."""
    wanted = set(days)
    slugs: list[str] = []
    for screening in parse(raw, days):
        slug = slug_of(screening.url)
        if slug and screening.day in wanted and slug not in slugs:
            slugs.append(slug)
            if len(slugs) > config.RODINA_MAX_EVENT_PAGES:
                log.warning("rodina: %d distinct films, fetching film pages for the first %d only",
                            len(slugs), config.RODINA_MAX_EVENT_PAGES)
                slugs = slugs[: config.RODINA_MAX_EVENT_PAGES]
    return slugs


def parse(raw: list[tuple[str, str]], days: list[date]) -> list[Screening]:
    """Every show-time anchor of the day pages, with the fragment as the truth about the start.

    The fragment dates may differ from the requested day (the platform also renders
    the nearest shows of neighbouring days on a day page), so screenings are NOT cut
    by `days` here — the pipeline applies the window itself. A seance rendered twice
    (gallery-slider badge and schedule-list row) is merged by (start, title): the
    first occurrence keeps its values, holes (url, hall, price, language, chips) are
    filled from the later one. Film pages («event:<slug>» bodies) fill the keys the
    day page did not give.
    """
    films: dict[str, dict] = {}
    merged: dict[tuple[datetime, str], Screening] = {}
    order: list[tuple[datetime, str]] = []
    for label, body in raw:
        if label.startswith(EVENT_LABEL_PREFIX):
            if body:
                films[label[len(EVENT_LABEL_PREFIX):]] = film_facts(body)
            continue
        source_url = _source_url(label)
        for screening in _page_screenings(body, source_url):
            key = (screening.start, screening.title)
            if key in merged:
                merged[key] = _merge(merged[key], screening)
            else:
                merged[key] = screening
                order.append(key)
    out: list[Screening] = []
    for key in order:
        screening = merged[key]
        facts = films.get(slug_of(screening.url) or "")
        if facts:
            screening = replace(screening, extra={**facts, **screening.extra})
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


def warning(raw: list[tuple[str, str]]) -> str | None:
    """How many film pages could not be fetched — shown as ⚠ in the status rows."""
    missing = sum(1 for label, body in raw if label.startswith(EVENT_LABEL_PREFIX) and not body)
    if not missing:
        return None
    return f"не загрузились страницы фильмов: {missing} — у их сеансов нет длительности и описания"


def film_facts(body: str) -> dict:
    """The schema.org Movie microdata of a /events/<slug> page → extra keys of the template."""
    try:
        soup = BeautifulSoup(body, "lxml")
    except Exception as exc:
        log.debug("rodina: film page could not be parsed (%s)", exc)
        return {}
    movie = soup.find(attrs={"itemtype": _MOVIE_RE})
    if movie is None:
        return {}
    facts: dict = {}
    for value in _item_values(movie, "dateCreated") + _item_values(movie, "datePublished"):
        match = re.search(r"(1[89]\d{2}|20\d{2})", value)
        if match:
            facts["year"] = int(match.group(1))
            break
    age = _age(next(iter(_item_values(movie, "contentRating")), None))
    if age:
        facts["age"] = age
    for value in _item_values(movie, "duration"):
        minutes = duration_minutes(value)
        if minutes:
            facts["duration_min"] = minutes
            break
    description = next(iter(_item_values(movie, "description")), None)
    if description:
        facts["synopsis"] = _shorten(description)
    directors = _item_values(movie, "director")
    if directors:
        facts["director"] = ", ".join(directors)
    genres = _item_values(movie, "genre")
    if genres:
        facts["genres"] = genres
    countries = _item_values(movie, "countryOfOrigin")
    if countries:
        facts["country"] = ", ".join(countries)
    return facts


def duration_minutes(text: str | None) -> int | None:
    """«1 час 32 минуты» → 92, «2 часа» → 120, «45 минут» → 45, «PT1H32M» → 92; None otherwise."""
    if not text:
        return None
    iso = _ISO_DURATION_RE.match(text.strip())
    if iso and (iso.group(1) or iso.group(2)):
        return int(iso.group(1) or 0) * 60 + int(iso.group(2) or 0) or None
    hours = _HOURS_RE.search(text)
    minutes = _MINUTES_RE.search(text)
    if hours is None and minutes is None:
        return None
    total = (int(hours.group(1)) if hours else 0) * 60 + (int(minutes.group(1)) if minutes else 0)
    return total or None


def _item_values(scope: Tag, prop: str) -> list[str]:
    values: list[str] = []
    for node in scope.find_all(attrs={"itemprop": prop}):
        value = _item_value(node)
        if value and value not in values:
            values.append(value)
    return values


def _item_value(node: Tag) -> str | None:
    if node.has_attr("itemscope"):
        name = node.find(attrs={"itemprop": "name"})
        node = name if name is not None else node
    if node.name == "meta" or node.has_attr("content"):
        value = node.get("content")
    else:
        value = node.get_text(" ", strip=True)
    return " ".join(str(value or "").split()) or None


def _age(value: str | None) -> str | None:
    if not value:
        return None
    match = _AGE_RE.match(value)
    return f"{match.group(1)}+" if match else None


def _shorten(text: str, limit: int = _SYNOPSIS_LIMIT) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > limit // 2 else limit].rstrip(" ,;:—-") + "…"


def _merge(first: Screening, second: Screening) -> Screening:
    """One seance rendered twice: every field keeps the first document occurrence, holes
    are filled from the later one, and the id follows the merged hall."""
    hall = first.hall or second.hall
    return replace(
        first,
        source_id=synthetic_id(ID, first.start, first.title, hall),
        hall=hall,
        price_min=first.price_min if first.price_min is not None else second.price_min,
        price_max=first.price_max if first.price_max is not None else second.price_max,
        language=first.language or second.language,
        tags=first.tags or second.tags,
        url=first.url or second.url,
        extra={**second.extra, **first.extra},
    )


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
    block, heading = _event_block(anchor)
    title = heading.get_text(" ", strip=True) if heading is not None else ""
    if not title:
        log.debug("rodina: anchor %r has no enclosing event block with a heading, skipped", anchor.get("href"))
        return None
    price = _price(show)
    hall = _hall(show)
    return Screening(
        venue=ID,
        source_id=synthetic_id(ID, start, title, hall),
        title=title,
        start=start,
        hall=hall,
        price_min=price,
        price_max=price,
        language=_language(show),
        tags=(),
        url=_event_url(block),
        source_url=source_url,
        extra=_event_facts(heading),
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


def _event_block(anchor: Tag) -> tuple[Tag | None, Tag | None]:
    """(enclosing block, heading): climb to the nearest ancestor that carries a heading
    and take its first heading (in document order). The same block is searched for the
    event link; the heading's neighbourhood carries the film chips."""
    node = anchor
    while node is not None:
        node = node.parent
        if node is None or node.name in ("body", "html"):
            break
        heading = node.find(_HEADINGS, recursive=True)
        if heading is not None:
            return node, heading
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


def _event_facts(heading: Tag | None) -> dict:
    """year / age / genres / country from the chips beside the event heading
    (data-tag="2026", "18+", "боевик", "Испания"). Capitalised chips are countries,
    lowercase chips genres; the hall chip of the schedule-list wrapper («Большой зал»)
    belongs to the show, not the film, and is skipped."""
    if heading is None or heading.parent is None:
        return {}
    facts: dict = {}
    genres: list[str] = []
    countries: list[str] = []
    for container in heading.parent.find_all("div", class_=_TAGS_RE):
        for chip in container.find_all("div", recursive=False):
            text = " ".join(str(chip.get("data-tag") or chip.get_text(" ", strip=True)).split())
            if not text or "зал" in text.lower():
                continue
            if _YEAR_CHIP_RE.match(text):
                facts.setdefault("year", int(text))
            elif _AGE_CHIP_RE.match(text):
                facts.setdefault("age", text)
            elif text[0].isupper():
                if text not in countries:
                    countries.append(text)
            elif text not in genres:
                genres.append(text)
    if genres:
        facts["genres"] = genres
    if countries:
        facts["country"] = ", ".join(countries)
    return facts


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


def _hall(show: Tag | None) -> str | None:
    """Hall of the show when the schedule-list wrapper renders it in a tags sibling
    («Большой зал», «Малый 2 зал»); the gallery-slider blocks have no such sibling,
    so their shows stay hall=None. Only texts naming a «зал» are accepted."""
    if show is None:
        return None
    parent = show.parent
    if parent is None:
        return None
    for sibling in parent.find_all("div", recursive=False):
        classes = sibling.get("class") or []
        if not any(_TAGS_RE.match(str(token)) for token in classes):
            continue
        text = " ".join(sibling.get_text(" ", strip=True).split())
        return text if "зал" in text else None
    return None
