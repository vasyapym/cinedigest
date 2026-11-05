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
