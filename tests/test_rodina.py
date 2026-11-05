"""Родина: разбор сохранённых дневных страниц, слияние дублей слайдер+список, факты о фильме, страницы фильмов и маркер «Сеансы не найдены»."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from cinedigest import config, render_text
from cinedigest.http import HttpError
from cinedigest.model import MSK, synthetic_id
from cinedigest.venues import rodina

FIXTURES = Path(__file__).parent / "fixtures" / "rodina"
DAY = "2026-11-07.html"
DAY_NOFACILITY = "2026-11-07-nofacility.html"
DAY_URL = "https://rodinakino.ru/?date=2026/11/07"
WINDOW = [date(2026, 11, 7)]


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _parse(body: str, label: str = "2026-11-07"):
    return rodina.parse([(label, body)], WINDOW)


def _show(slug: str, time_: str, *, price: bool = True, hall: str | None = None, sub: bool = False, chips: tuple[str, ...] = (), link: bool = True) -> str:
    """One event block of the day page: show wrapper (+ optional hall chip) and event heading."""
    title = f'<a class="event-name" href="/events/{slug}?facility=deadbeef">Фильм {slug}</a>' if link else f"Фильм {slug}"
    hall_html = (f'<div class="EventShowsList_tags__TmGHt"><div class="EventShowsList_tag__moy5K">{hall}</div></div>'
                 if hall else "")
    price_html = '<div class="Show_price__YStM_ price">300\u2009₽</div>' if price else ""
    sub_html = '<span class="show-format" data-format="SUB">SUB</span>' if sub else ""
    chips_html = "".join(f'<div class="EventShowsList_tag__moy5K" data-tag="{c}">{c}</div>' for c in chips)
    return (
        '<div class="EventShowsList_wrap__KvU6E event">'
        '<div class="EventShowsList_show__pQ3_7">'
        '<div class="Show_show__kEocF show">'
        f'<a href="?date=2026/11/07&amp;facility=deadbeef#2026/11/07 {time_}">'
        f'<div class="Show_show-time__iv3r5 show-time">{time_}</div></a>'
        f'<div class="Show_show-info__CN3vZ">{price_html}<div class="Show_formats__D01T_ formats">{sub_html}</div></div>'
        "</div>"
        f"{hall_html}"
        "</div>"
        '<div class="EventShowsList_event__nLeul">'
        f'<h2 class="Title_title__GSkiG title">{title}</h2>'
        f'<div class="EventShowsList_tags__TmGHt">{chips_html}</div>'
        "</div>"
        "</div>"
    )


def _page(*blocks: str) -> str:
    return '<html><body><div class="page">' + "".join(blocks) + "</div></body></html>"


def _movie_page(*, year: str = "1961", rating: str = "12", duration: str = "1 час 32 минуты",
                description: str = "Однажды талантливый учёный доктор Сальватор спас жизнь мальчику.") -> str:
    return (
        '<html><body><div itemScope="" itemType="http://schema.org/Movie">'
        '<meta itemProp="name" content="Человек-амфибия"/>'
        '<meta itemProp="image" content="https://cdn.p24.app/r/ps/poster.jpg"/>'
        f'<meta itemProp="contentRating" content="{rating}"/>'
        f'<meta itemProp="duration" content="{duration}"/>'
        f'<meta itemProp="dateCreated" content="{year}"/>'
        f'<meta itemProp="description" content="{description}"/>'
        '<meta itemProp="genre" content="драма"/><meta itemProp="genre" content="фантастика"/>'
        '<meta itemProp="director" content="Владимир Чеботарев"/><meta itemProp="director" content="Геннадий Казанский"/>'
        '<meta itemProp="actor" content="Владимир Коренев"/>'
        "</div></body></html>"
    )


class _FakeHttp:
    def __init__(self, bodies: dict[str, str], failing: set[str] = frozenset()):
        self.bodies = bodies
        self.failing = set(failing)
        self.calls: list[str] = []
        self.request_count = 0

    def get(self, url, *, params=None, headers=None, venue="", label=""):
        self.calls.append(url)
        self.request_count += 1
        if url in self.failing:
            raise HttpError("HTTP 503", url=url, status=503)
        return self.bodies[url]


def test_day_url_pattern():
    assert rodina.day_url(date(2026, 11, 7)) == DAY_URL
    assert rodina.event_url("idealnyj-shtorm-2026") == "https://rodinakino.ru/events/idealnyj-shtorm-2026"
    assert rodina.slug_of("https://rodinakino.ru/events/idealnyj-shtorm-2026?facility=x") == "idealnyj-shtorm-2026"
    assert rodina.slug_of(None) is None and rodina.slug_of(DAY_URL) is None


def test_day_fixture_parses_forty_nine_unique_screenings():
    items = _parse(_body(DAY))
    # 50 якорей с фрагментами; один сеанс стоит на странице дважды
    # («Шоссе в никуда. АртПоказ» 19:05 — в слайдере и в списке), дубли сливаются в одну строку.
    assert len(items) == 49
    ids = [s.source_id for s in items]
    assert len(set(ids)) == len(ids)
    for screening in items:
        assert screening.venue == "rodina"
        assert screening.hall is None or "зал" in screening.hall
        assert screening.tags == ()
        assert screening.source_url == DAY_URL
        assert screening.start.tzinfo is MSK
    # Залы есть у строк основного списка (15 строк в этом дне) плюс у слитого дубля,
    # если его списочный вариант несёт зал.
    expected = {"Большой зал": 5, "Малый 1 зал": 6, "Малый 2 зал": 4}
    schosse = next(s for s in items if s.title == "Шоссе в никуда. АртПоказ" and s.start == datetime(2026, 11, 7, 19, 5, tzinfo=MSK))
    if schosse.hall:
        expected[schosse.hall] = expected.get(schosse.hall, 0) + 1
    counts: dict[str, int] = {}
    for s in items:
        if s.hall:
            counts[s.hall] = counts.get(s.hall, 0) + 1
    assert counts == expected


def test_fragment_dates_rule_over_request_date():
    items = _parse(_body(DAY))
    days = sorted({s.start.date() for s in items})
    # Страница часто показывает «ближайшие» сеансы соседних дней — дата берётся из фрагмента.
    assert date(2026, 11, 5) in days
    assert date(2026, 11, 7) in days
    assert len(days) >= 10


def test_pinned_example_rows():
    items = _parse(_body(DAY))
    keyed = {(s.title, s.start): s for s in items}

    # Большой список: цена «250 ₽» (тонкий пробел), зал из соседнего блока, ссылка на фильм
    # и чипы события: возраст, год, жанры, страна.
    storm = keyed[("Идеальный шторм", datetime(2026, 11, 7, 10, 5, tzinfo=MSK))]
    assert (storm.price_min, storm.price_max) == (250, 250)
    assert storm.language is None
    assert storm.hall == "Большой зал"
    assert storm.url == "https://rodinakino.ru/events/idealnyj-shtorm-2026"
    assert storm.source_id == synthetic_id("rodina", storm.start, "Идеальный шторм", "Большой зал")
    assert storm.extra == {"year": 2026, "age": "18+", "genres": ["боевик", "триллер", "драма", "детектив", "приключения"], "country": "Испания"}
    assert render_text.row(storm) == "10:05 · Родина · Идеальный шторм (2026) · 18+ · Большой зал · 250 ₽"

    pegas = keyed[("Большие гонки. Пегас III", datetime(2026, 11, 7, 10, 10, tzinfo=MSK))]
    assert (pegas.price_min, pegas.price_max) == (250, 250)
    assert pegas.hall == "Малый 2 зал"
    assert pegas.url == "https://rodinakino.ru/events/bolshie-gonki-pegas-iii-2026"
    assert pegas.extra.get("year") == 2026

    # Слайдерный показ соседнего дня: бейдж SUB входит в language, цены, зала и /events/ нет.
    french = keyed[("Безумный день в Комеди Франсез", datetime(2026, 11, 5, 17, 50, tzinfo=MSK))]
    assert french.language == "SUB"
    assert (french.price_min, french.price_max) == (None, None)
    assert french.hall is None
    assert french.url is None

    # Дубль слайдер+список: слайдерный SUB остаётся, дыры долиты из строки списка.
    schosse = [s for s in items if s.title == "Шоссе в никуда. АртПоказ" and s.start == datetime(2026, 11, 7, 19, 5, tzinfo=MSK)]
    assert len(schosse) == 1
    assert schosse[0].language == "SUB"
    assert schosse[0].url is not None and schosse[0].url.startswith("https://rodinakino.ru/events/")
    assert schosse[0].hall is not None and "зал" in schosse[0].hall
    assert schosse[0].price_min is not None
    assert schosse[0].source_id == synthetic_id("rodina", schosse[0].start, schosse[0].title, schosse[0].hall)


def test_range_of_prices_from_fixture():
    items = _parse(_body(DAY))
    prices = sorted({s.price_min for s in items if s.price_min is not None})
    assert 250 <= min(prices) and max(prices) <= 600
    for screening in items:
        assert screening.price_min == screening.price_max


def test_variants_with_and_without_facility_parse_identically():
    with_items = _parse(_body(DAY))
    without_items = _parse(_body(DAY_NOFACILITY))
    assert with_items == without_items
    assert len(with_items) == 49


def test_percent_encoded_fragment_is_accepted():
    body = (
        '<div class="page">'
        '<div class="EventShowsList_event-show__NSwpU event">'
        '<h2 class="Title_title__GSkiG title">'
        '<a class="event-name" href="/events/test-event-2026?facility=deadbeef">Тестовый сеанс</a>'
        '</h2>'
        '<div class="Show_show__kEocF show">'
        '<div class="Tooltip_wrapper__1WDa7 tooltip-wrapper">'
        '<a href="?date=2026/11/07&amp;facility=deadbeef#2026/11/07%2020%3A15">'
        '<div class="Show_show-time__iv3r5 show-time">20:15</div></a>'
        '</div>'
        '<div class="Show_show-info__CN3vZ">'
        '<div class="Show_price__YStM_ price">300\u2009₽</div>'
        '<div class="Show_formats__D01T_ formats">'
        '<span class="show-format" data-format="SUB">SUB</span>'
        '</div>'
        '</div>'
        '</div>'
        '</div>'
        '</div>'
    )
    items = _parse(body)
    assert len(items) == 1
    show = items[0]
    assert show.title == "Тестовый сеанс"
    assert show.start == datetime(2026, 11, 7, 20, 15, tzinfo=MSK)
    assert (show.price_min, show.price_max) == (300, 300)
    assert show.language == "SUB"
    assert show.hall is None  # блок без соседа с текстом «… зал»
    assert show.url == "https://rodinakino.ru/events/test-event-2026"
    assert show.source_url == f"{config.RODINA_SITE_URL}?date=2026/11/07"
    assert show.extra == {}


def test_slider_duplicate_is_filled_from_the_list_row():
    # Слайдер идёт первым (без цены, ссылки и зала), строка списка — второй.
    body = _page(
        _show("x-2026", "19:05", price=False, link=False, sub=True),
        _show("x-2026", "19:05", hall="Малый 1 зал", chips=("18+", "2026", "драма", "США", "Большой зал")),
    )
    items = _parse(body)
    assert len(items) == 1
    merged = items[0]
    assert merged.language == "SUB"
    assert (merged.price_min, merged.price_max) == (300, 300)
    assert merged.hall == "Малый 1 зал"
    assert merged.url == "https://rodinakino.ru/events/x-2026"
    assert merged.extra == {"year": 2026, "age": "18+", "genres": ["драма"], "country": "США"}
    assert merged.source_id == synthetic_id("rodina", merged.start, merged.title, "Малый 1 зал")

    # Обратный порядок даёт ту же строку.
    reverse = _parse(_page(
        _show("x-2026", "19:05", hall="Малый 1 зал", chips=("18+", "2026", "драма", "США", "Большой зал")),
        _show("x-2026", "19:05", price=False, link=False, sub=True),
    ))
    assert reverse == items


def test_event_page_facts_fill_missing_keys_only():
    raw = [
        ("2026-11-07", _page(_show("amfibia", "20:00", chips=("2026", "мелодрама")))),
        ("event:amfibia", _movie_page()),
        ("event:unknown", ""),  # неудачная загрузка — пустое тело
    ]
    items = rodina.parse(raw, WINDOW)
    assert len(items) == 1
    x = items[0].extra
    assert x["year"] == 2026  # чип дневной страницы сильнее страницы фильма
    assert x["genres"] == ["мелодрама"]
    assert x["age"] == "12+"
    assert x["duration_min"] == 92
    assert x["director"] == "Владимир Чеботарев, Геннадий Казанский"
    assert x["synopsis"].startswith("Однажды талантливый учёный")
    assert "country" not in x
    assert rodina.warning(raw) == "не загрузились страницы фильмов: 1 — у их сеансов нет длительности и описания"
    assert rodina.warning(raw[:2]) is None
    assert rodina.film_facts("<html><body>нет микроданных</body></html>") == {}
    long = rodina.film_facts(_movie_page(description="слово " * 200))["synopsis"]
    assert len(long) <= 321 and long.endswith("…")


def test_duration_minutes():
    assert rodina.duration_minutes("1 час 32 минуты") == 92
    assert rodina.duration_minutes("2 часа") == 120
    assert rodina.duration_minutes("45 минут") == 45
    assert rodina.duration_minutes("PT1H32M") == 92
    assert rodina.duration_minutes("PT95M") == 95
    assert rodina.duration_minutes("") is None
    assert rodina.duration_minutes("без длительности") is None


def test_event_slugs_cover_only_linked_window_rows():
    raw = [("2026-11-07", _body(DAY))]
    slugs = rodina.event_slugs(raw, WINDOW)
    assert "idealnyj-shtorm-2026" in slugs and "bolshie-gonki-pegas-iii-2026" in slugs
    assert len(slugs) == len(set(slugs)) <= config.RODINA_MAX_EVENT_PAGES
    linked = {rodina.slug_of(s.url) for s in rodina.parse(raw, WINDOW) if s.url and s.day == date(2026, 11, 7)}
    assert set(slugs) == linked


def test_fetch_requests_each_film_once_and_stops_after_failures():
    day = date(2026, 11, 7)
    body = _page(_show("a", "10:00"), _show("a", "12:00"), _show("b", "14:00"), _show("c", "16:00"),
                 _show("d", "18:00"), _show("e", "20:00"))
    bodies = {rodina.day_url(day): body}
    for slug in "abcde":
        bodies[rodina.event_url(slug)] = _movie_page(year="2001")
    http = _FakeHttp(bodies)
    raw = rodina.fetch(http, [day])
    assert [label for label, _ in raw] == ["2026-11-07"] + [f"event:{s}" for s in "abcde"]
    assert http.calls == [rodina.day_url(day)] + [rodina.event_url(s) for s in "abcde"]
    items = rodina.parse(raw, [day])
    assert len(items) == 6 and all(s.extra["year"] == 2001 and s.extra["duration_min"] == 92 for s in items)
    assert rodina.warning(raw) is None
    failing = {rodina.event_url(s) for s in "abcde"}
    http = _FakeHttp(bodies, failing=failing)
    raw = rodina.fetch(http, [day])
    attempted = list("abcde")[:config.RODINA_EVENT_FAILURE_LIMIT]
    assert http.calls == [rodina.day_url(day)] + [rodina.event_url(s) for s in attempted]
    assert [label for label, _ in raw] == ["2026-11-07"] + [f"event:{s}" for s in "abcde"]
    assert all(not body for label, body in raw if label.startswith("event:"))
    assert rodina.warning(raw) == "не загрузились страницы фильмов: 5 — у их сеансов нет длительности и описания"
    items = rodina.parse(raw, [day])
    assert len(items) == 6
    assert all("duration_min" not in s.extra for s in items)


def test_fetch_failure_limit_counts_total_failures_not_consecutive(monkeypatch):
    monkeypatch.setattr(config, "RODINA_EVENT_FAILURE_LIMIT", 2)
    body = _page(
        _show("a", "10:00"),
        _show("b", "12:00"),
        _show("c", "14:00"),
        _show("d", "16:00"),
    )
    bodies = {DAY_URL: body}
    bodies.update({rodina.event_url(s): _movie_page() for s in "abcd"})
    http = _FakeHttp(bodies, failing={rodina.event_url("a"), rodina.event_url("c")})

    raw = rodina.fetch(http, WINDOW)

    assert http.calls == [DAY_URL] + [rodina.event_url(s) for s in "abc"]
    assert [label for label, _ in raw] == [
        "2026-11-07", "event:a", "event:b", "event:c", "event:d",
    ]
    assert dict(raw)["event:b"] == _movie_page()
    assert all(dict(raw)[f"event:{s}"] == "" for s in "acd")
    assert rodina.warning(raw) == "не загрузились страницы фильмов: 3 — у их сеансов нет длительности и описания"
    keyed = {s.title: s for s in rodina.parse(raw, WINDOW)}
    assert keyed["Фильм b"].extra["duration_min"] == 92
    assert all("duration_min" not in keyed[f"Фильм {s}"].extra for s in "acd")


def test_fetch_zero_failure_budget_keeps_schedule_without_event_requests(monkeypatch):
    monkeypatch.setattr(config, "RODINA_EVENT_FAILURE_LIMIT", 0)
    body = _page(_show("a", "10:00"), _show("b", "12:00"))
    http = _FakeHttp({DAY_URL: body})

    raw = rodina.fetch(http, WINDOW)

    assert http.calls == [DAY_URL]
    assert raw == [("2026-11-07", body), ("event:a", ""), ("event:b", "")]
    assert len(rodina.parse(raw, WINDOW)) == 2
    assert rodina.warning(raw) == "не загрузились страницы фильмов: 2 — у их сеансов нет длительности и описания"


def test_event_slugs_cap_preserves_document_order_and_fetch_bound(monkeypatch):
    monkeypatch.setattr(config, "RODINA_MAX_EVENT_PAGES", 2)
    body = _page(
        _show("b", "10:00"),
        _show("a", "12:00"),
        _show("b", "14:00"),
        _show("c", "16:00"),
        _show("d", "18:00"),
    )
    assert rodina.event_slugs([("2026-11-07", body)], WINDOW) == ["b", "a"]

    bodies = {DAY_URL: body}
    bodies.update({rodina.event_url(s): _movie_page() for s in "ab"})
    http = _FakeHttp(bodies)
    raw = rodina.fetch(http, WINDOW)

    assert http.calls == [DAY_URL, rodina.event_url("b"), rodina.event_url("a")]
    assert [label for label, _ in raw] == ["2026-11-07", "event:b", "event:a"]
    assert rodina.warning(raw) is None
    items = rodina.parse(raw, WINDOW)
    assert len(items) == 5
    assert all(
        ("duration_min" in s.extra) == (s.title in {"Фильм a", "Фильм b"})
        for s in items
    )


def test_real_event_page_facts_and_enrichment():
    body = _body("event-chelovek-amfibiya-1961g-lenfilm-1961.html")
    facts = rodina.film_facts(body)

    assert set(facts) == {
        "year", "age", "duration_min", "synopsis", "director", "genres",
    }
    assert facts["year"] == 1961
    assert facts["age"] == "12+"
    assert facts["duration_min"] == 92
    assert facts["director"] == "Владимир Чеботарев, Геннадий Казанский"
    assert facts["genres"] == ["драма", "мелодрама", "фантастика"]
    assert facts["synopsis"].startswith(
        "Однажды талантливый учёный доктор Сальватор спас жизнь маленькому мальчику"
    )
    assert facts["synopsis"].endswith("…")
    assert len(facts["synopsis"]) <= 321
    assert "country" not in facts

    slug = "chelovek-amfibiya-1961g-lenfilm-1961"
    raw = [
        ("2026-11-07", _page(_show(slug, "20:00"))),
        (f"event:{slug}", body),
    ]
    items = rodina.parse(raw, WINDOW)
    assert len(items) == 1
    assert items[0].extra == facts
    assert rodina.warning(raw) is None


def test_legit_empty_requires_rendered_marker_not_hidden_dictionary():
    assert rodina.legit_empty(
        "<html><body><p>Сеансы не найдены</p></body></html>"
    ) is True
    assert rodina.legit_empty(
        '<html><body><script>{"empty": "Сеансы не найдены"}</script></body></html>'
    ) is False
    assert rodina.legit_empty(
        "<html><body><style>/* Сеансы не найдены */</style>"
        "<noscript>Сеансы не найдены</noscript></body></html>"
    ) is False
    assert rodina.legit_empty(_body(DAY)) is False
    assert rodina.legit_empty("") is False
    assert rodina.legit_empty("<html><body>Ошибка сервера</body></html>") is False


def test_invalid_fragments_and_anchors_without_heading_are_skipped():
    invalid_date = _show("bad-date", "10:00").replace(
        "#2026/11/07 10:00", "#2026/13/07 10:00"
    )
    invalid_time = _show("bad-time", "25:99")
    malformed_fragment = _show("bad-fragment", "12:00").replace(
        "#2026/11/07 12:00", "#not-a-date"
    )
    body = (
        "<html><body>"
        '<div><a href="#2026/11/07%2011%3A00">Без заголовка</a></div>'
        + invalid_date
        + invalid_time
        + malformed_fragment
        + _show("ok", "18:00")
        + "</body></html>"
    )
    items = _parse(body)
    assert [(s.title, s.start) for s in items] == [
        ("Фильм ok", datetime(2026, 11, 7, 18, 0, tzinfo=MSK)),
    ]


def test_fetch_day_error_is_not_swallowed():
    import pytest

    http = _FakeHttp({}, failing={DAY_URL})
    with pytest.raises(HttpError):
        rodina.fetch(http, WINDOW)
    assert http.calls == [DAY_URL]
