"""Родина: разбор сохранённых дневных страниц и её маркер «Сеансы не найдены»."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK, synthetic_id
from cinedigest.venues import rodina

FIXTURES = Path(__file__).parent / "fixtures" / "rodina"
DAY = "2026-11-07.html"
DAY_NOFACILITY = "2026-11-07-nofacility.html"
DAY_URL = "https://rodinakino.ru/?date=2026/11/07"


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _parse(body: str, label: str = "2026-11-07"):
    return rodina.parse([(label, body)], [date(2026, 11, 7)])


def test_day_url_pattern():
    assert rodina.day_url(date(2026, 11, 7)) == DAY_URL


def test_day_fixture_parses_forty_nine_unique_screenings():
    items = _parse(_body(DAY))
    # 50 якорей с фрагментами; один сеанс стоит на странице дважды
    # («Шоссе в никуда. АртПоказ» 19:05 — в слайдере и в списке), дедуп оставляет первое.
    assert len(items) == 49
    ids = [s.source_id for s in items]
    assert len(set(ids)) == len(ids)
    for screening in items:
        assert screening.venue == "rodina"
        assert screening.hall is None
        assert screening.tags == ()
        assert screening.source_url == DAY_URL
        assert screening.start.tzinfo is MSK


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

    # Большой список: цена «250 ₽» (тонкий пробел) и рядом ссылка на фильм.
    storm = keyed[("Идеальный шторм", datetime(2026, 11, 7, 10, 5, tzinfo=MSK))]
    assert (storm.price_min, storm.price_max) == (250, 250)
    assert storm.language is None
    assert storm.url == "https://rodinakino.ru/events/idealnyj-shtorm-2026"
    assert storm.source_id == synthetic_id("rodina", storm.start, "Идеальный шторм", None)

    pegas = keyed[("Большие гонки. Пегас III", datetime(2026, 11, 7, 10, 10, tzinfo=MSK))]
    assert (pegas.price_min, pegas.price_max) == (250, 250)
    assert pegas.url == "https://rodinakino.ru/events/bolshie-gonki-pegas-iii-2026"

    # Слайдерный показ: бейдж SUB входит в language, цены в блоке нет, /events/ рядом нет.
    french = keyed[("Безумный день в Комеди Франсез", datetime(2026, 11, 5, 17, 50, tzinfo=MSK))]
    assert french.language == "SUB"
    assert (french.price_min, french.price_max) == (None, None)
    assert french.url is None

    schosse = [s for s in items if s.title == "Шоссе в никуда. АртПоказ" and s.start == datetime(2026, 11, 7, 19, 5, tzinfo=MSK)]
    assert len(schosse) == 1  # дубль слайдер+список схлопнут первым вхождением
    assert (schosse[0].language, schosse[0].price_min) == ("SUB", None)


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
    assert show.url == "https://rodinakino.ru/events/test-event-2026"
    assert show.source_url == f"{config.RODINA_SITE_URL}?date=2026/11/07"


def test_legit_empty_shapes():
    assert rodina.legit_empty("<html><body><p>Сеансы не найдены</p></body></html>") is True
    # В дневных файлах фраза живёт только в i18n-словаре внутри <script> — это НЕ пустой день.
    assert rodina.legit_empty(_body(DAY)) is False
    assert rodina.legit_empty(_body(DAY_NOFACILITY)) is False
    assert rodina.legit_empty('<html><body><script>var t="Сеансы не найдены";</script></body></html>') is False
    assert rodina.legit_empty("") is False
