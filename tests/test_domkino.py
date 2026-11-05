"""Дом кино: разбор сохранённых страниц-расписаний и его форма «пустого дня»."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK, synthetic_id
from cinedigest.venues import domkino

FIXTURES = Path(__file__).parent / "fixtures" / "domkino"
DAY = "2026-11-06.html"
DAY_URL = "https://www.domkino.spb.ru/schedule/2026/11/06/"


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _day_items():
    return domkino.parse([("2026-11-06", _body(DAY))], [date(2026, 11, 6)])


def test_day_url_pattern():
    assert domkino.day_url(date(2026, 11, 6)) == DAY_URL


def test_november_6_parses_all_thirty_screenings():
    items = _day_items()
    # 30 строк расписания в разметке — на каждый из пяти залов ровно 6 показов.
    assert len(items) == 30
    per_hall: dict[str, int] = {}
    for screening in items:
        per_hall[screening.hall] = per_hall.get(screening.hall, 0) + 1
        assert screening.venue == "domkino"
        assert screening.tags == ()
        assert screening.source_url == DAY_URL
        assert screening.day == date(2026, 11, 6)
        assert screening.start.tzinfo is MSK
    assert per_hall == {
        "Большой зал": 6,
        "Синий зал": 6,
        "Белый зал": 6,
        "Сиреневый зал": 6,
        "Малый зал": 6,
    }


def test_pinned_example_rows():
    items = _day_items()
    assert items[0].source_id == synthetic_id("domkino", items[0].start, items[0].title, items[0].hall)
    keyed = {(s.title, s.start): s for s in items}
    assert len(keyed) == len(items)  # ни одной пары-дубля на странице

    # Большой зал, 10:30 — цена «350/200» берётся первым числом, звук дословно.
    sacrifice = keyed[("Жертвоприношение", datetime(2026, 11, 6, 10, 30, tzinfo=MSK))]
    assert (sacrifice.price_min, sacrifice.price_max) == (350, 350)
    assert sacrifice.extra["genres"] == ["драма"]
    assert sacrifice.language == "закадровый"
    assert sacrifice.hall == "Большой зал"
    assert sacrifice.url == "https://www.domkino.spb.ru/films/zhertvoprinoshenie/"

    # Большой зал, 13:15 — «дублирование» остаётся дословной формулировкой, не SUB.
    vkuskill = keyed[("Вкускилл", datetime(2026, 11, 6, 13, 15, tzinfo=MSK))]
    assert vkuskill.language == "дублирование"
    assert vkuskill.extra["genres"] == ["ужасы"]
    assert (vkuskill.price_min, vkuskill.price_max) == (400, 400)
    assert vkuskill.hall == "Большой зал"

    # Синий зал, 15:30 — жанры разбиты по запятым, «русские субтитры» не превращаются в SUB.
    bugonia = keyed[("Бугония (субтитры, билеты только в кассе кинотеатра)", datetime(2026, 11, 6, 15, 30, tzinfo=MSK))]
    assert bugonia.hall == "Синий зал"
    assert bugonia.language == "английский, русские субтитры"
    assert bugonia.extra["genres"] == ["комедия", "фантастика"]
    assert (bugonia.price_min, bugonia.price_max) == (450, 450)
    assert bugonia.url == "https://www.domkino.spb.ru/films/bugoniya_subtitry/"

    # Малый зал, 11:45 — пустые ячейки жанра и звука ни на что не ссылаются.
    nadezhda = keyed[("Надежда (субтитры)", datetime(2026, 11, 6, 11, 45, tzinfo=MSK))]
    assert nadezhda.hall == "Малый зал"
    assert nadezhda.language is None
    assert "genres" not in nadezhda.extra
    assert (nadezhda.price_min, nadezhda.price_max) == (250, 250)
    assert nadezhda.url == "https://www.domkino.spb.ru/films/nadezhda_subtitry/"


def test_no_language_ever_becomes_sub():
    for screening in _day_items():
        assert screening.language != "SUB"


def test_legit_empty_shapes():
    # Оболочка дальнего дня: 200, без заголовков залов, но это страница расписания.
    assert domkino.legit_empty(_body("2027-01-10.html")) is True
    # Обычный день с залами — не пустой.
    assert domkino.legit_empty(_body(DAY)) is False
    # Не страница расписания (без слова «Расписание») — подозрительная форма.
    assert domkino.legit_empty("<html><body><p>Дом кино сегодня не отвечает</p></body></html>") is False
    assert domkino.legit_empty("") is False


def test_shell_day_parses_to_nothing_and_is_legit():
    label = "2027-01-10"
    days = [date(2027, 1, 10)]
    body = _body("2027-01-10.html")
    assert domkino.parse([(label, body)], days) == []
    # Само «подозрение» снято формой legit_empty (как делает pipeline для DAILY-адаптеров).
    assert domkino.legit_empty(body) is True


def test_schedule_page_without_hall_headings_yields_nothing_but_is_legit():
    body = (
        '<html><head><title>Расписание / Дом Кино</title></head>'
        '<body><div class="menu"><p>Дом Кино</p></div></body></html>'
    )
    label = "2026-11-06"
    items = domkino.parse([(label, body)], [date(2026, 11, 6)])
    assert items == []
    assert domkino.legit_empty(body) is True


def test_broken_rows_are_skipped_without_crash():
    body = (
        '<html><head><title>Расписание / Дом Кино</title></head><body>'
        '<h3>Большой зал</h3><table><tr>'
        '<td class="s_hd">25:99</td><td class="f_hd">Хмурое утро</td><td class="z_hd"></td>'
        '<td class="d_hd"></td><td class="p_hd"></td>'  # неосуществимое время
        '</tr></table><table><tr>'
        '<td class="s_hd">12:00</td><td class="f_hd"></td>'  # два кортежа ячеек и пустой заголовок
        '</tr><tr><td class="s_hd">13:00</td><td class="f_hd">Окей</td><td class="z_hd">драма</td>'
        '<td class="d_hd">оригинальный</td><td class="p_hd">200 руб.</td></tr></table>'
        '</body></html>'
    )
    items = domkino.parse([("2026-11-06", body)], [date(2026, 11, 6)])
    assert [(s.title, s.start, s.language, s.price_min) for s in items] == [
        ("Окей", datetime(2026, 11, 6, 13, 0, tzinfo=MSK), "оригинальный", 200),
    ]


def test_pinned_film_card_facts():
    keyed = {(s.title, s.start): s for s in _day_items()}
    sacrifice = keyed[("Жертвоприношение", datetime(2026, 11, 6, 10, 30, tzinfo=MSK))]
    assert sacrifice.extra == {
        "year": 1986,
        "country": "Швеция, Франция, Великобритания",
        "duration_min": 149,
        "age": "18+",
        "original_title": "Offret",
        "director": "Андрей Тарковский",
        "genres": ["драма"],
    }

    vkuskill = keyed[("Вкускилл", datetime(2026, 11, 6, 13, 15, tzinfo=MSK))]
    assert vkuskill.extra == {
        "year": 2026,
        "country": "Япония",
        "duration_min": 88,
        "age": "18+",
        "original_title": "チルド",
        "director": "Юсукэ Ивасаки",
        "genres": ["ужасы"],
    }


def test_year_coverage_from_real_cards():
    items = _day_items()
    with_year = [s for s in items if "year" in s.extra]
    assert len(with_year) == 28
    assert {s.extra["year"] for s in with_year} == {
        1960, 1966, 1983, 1986, 1991, 2006, 2023, 2024, 2025, 2026,
    }
    assert all(isinstance(s.extra["year"], int) for s in with_year)


def _row(clock: str, title_html: str, genres: str = "", language: str = "",
         price: str = "") -> str:
    return (
        f"<tr><td>{clock}</td><td>{title_html}</td><td>{genres}</td>"
        f"<td>{language}</td><td>{price}</td></tr>"
    )


def _parse_synthetic(body: str):
    return domkino.parse([("2026-11-06", body)], [date(2026, 11, 6)])


def test_title_link_wins_and_card_link_is_fallback():
    body = (
        "<html><body><h3>Большой зал</h3><table>"
        + _row("10:00", '<a href="/films/row-film/">Из строки</a>', "драма")
        + _row("12:00", "Из карточки", "комедия")
        + "</table>"
        '<div><a href="/films/card-film/">Подробнее</a>'
        "<p>2026 / Россия / драма</p></div>"
        "</body></html>"
    )
    items = _parse_synthetic(body)
    assert len(items) == 2
    assert items[0].url == config.DOMKINO_SITE_URL + "films/row-film/"
    assert items[1].url == config.DOMKINO_SITE_URL + "films/card-film/"
    assert items[0].extra == {"year": 2026, "country": "Россия", "genres": ["драма"]}
    assert items[1].extra == {"year": 2026, "country": "Россия", "genres": ["комедия"]}


def test_film_card_walk_stops_at_next_table_and_hall():
    # Карточка второй таблицы не должна попасть ни в первую, ни в следующий зал.
    body = (
        "<html><body><h3>Большой зал</h3><table>"
        + _row("10:00", "Без карточки")
        + "</table><table>"
        + _row("12:00", "Со своей карточкой")
        + "</table>"
        '<div><a href="/films/second/">Подробнее</a>'
        "<p>2006 / Франция / драма</p>"
        '<span class="duration">95 мин.</span></div>'
        "<h3>Синий зал</h3><table>"
        + _row("14:00", "Другой зал")
        + "</table></body></html>"
    )
    items = _parse_synthetic(body)
    assert len(items) == 3
    assert items[0].extra == {}
    assert items[0].url is None
    assert items[1].extra == {
        "year": 2006, "country": "Франция", "duration_min": 95,
    }
    assert items[1].url == config.DOMKINO_SITE_URL + "films/second/"
    assert items[2].hall == "Синий зал"
    assert items[2].extra == {}
    assert items[2].url is None


def test_broken_row_guard_requires_five_cells_and_nonempty_title():
    body = (
        "<html><body><h3>Большой зал</h3><table>"
        "<tr><th>Время</th><th>Фильм</th></tr>"
        "<tr><td>10:00</td><td>Четыре ячейки</td><td></td><td></td></tr>"
        "<tr><td>11:00</td><td>Шесть ячеек</td><td></td><td></td><td></td><td></td></tr>"
        + _row("12:00", "   ")
        + _row("25:00", "Неверный час")
        + _row("13:60", "Неверная минута")
        + _row("не время", "Неверная строка")
        + _row("14:00", "Окей", "драма, комедия", "", "нет цены")
        + "</table></body></html>"
    )
    items = _parse_synthetic(body)
    assert len(items) == 1
    assert items[0].title == "Окей"
    assert items[0].start == datetime(2026, 11, 6, 14, 0, tzinfo=MSK)
    assert items[0].extra == {"genres": ["драма", "комедия"]}
    assert items[0].language is None
    assert items[0].price_min is None and items[0].price_max is None
    assert domkino.legit_empty(body) is False
