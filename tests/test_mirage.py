"""Мираж на Большом: сохранённые страницы сети, выбор филиала, дата, билеты и формы пустого дня."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK, synthetic_id
from cinedigest.venues import mirage

FIXTURES = Path(__file__).parent / "fixtures" / "mirage"
DAY = "2026-11-07.html"
PREVIOUS_DAY = "2026-11-06.html"
DAY_URL = "https://www.mirage.ru/spb/schedule/07.11.2026/"
WINDOW = [date(2026, 11, 7)]
TICKET = "00000000-0000-4000-8000-000000000001"
OTHER_TICKET = "00000000-0000-4000-8000-000000000002"
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _parse(body: str, label: str = "2026-11-07"):
    return mirage.parse([(label, body)], WINDOW)


def _day_items():
    return _parse(_body(DAY))


def _session(*, title: str = "Тестовый фильм", clock: str = "12:30",
             hall: str = "Зал №2", fmt: str = "2D",
             price_raw: str | None = "450₽", genres: str = "драма, комедия",
             age: str = "18+", film_id: int | None = 1234,
             ticket: str | None = TICKET) -> str:
    price_html = f'<div class="place-price">{price_raw}</div>' if price_raw is not None else ""
    photo_html = (
        f'<div class="photo"><img src="/images/posters/p{film_id}.jpg"/></div>'
        if film_id is not None else ""
    )
    ticket_html = (
        f'<a href="/ticket_new/{ticket}/">Купить билет</a>'
        if ticket is not None else ""
    )
    return (
        '<div class="session">'
        f'<div class="title">{title}</div>'
        f'<div class="info-line"><span class="time">{clock}</span></div>'
        f'<div class="labels"><span>{hall}</span></div>'
        f'<div class="format">{fmt}</div>'
        f'<div class="genre">{genres}</div>'
        f'<div class="age">{age}</div>'
        f"{price_html}{photo_html}{ticket_html}"
        "</div>"
    )


def _branch(content: str = "", *, name: str = "НА БОЛЬШОМ",
            href: str | None = "/spb/cinema/1/") -> str:
    title = f'<a href="{href}">{name}</a>' if href is not None else name
    return (
        '<div class="session-box">'
        f'<div class="md-title">{title}</div>'
        f"{content}</div>"
    )


def _page(*boxes: str, active: str = "07.11.2026") -> str:
    return (
        "<html><body>"
        f'<a class="date-tab active" href="/spb/schedule/{active}/">{active}</a>'
        + "".join(boxes)
        + "</body></html>"
    )


def test_day_url_pattern():
    assert mirage.day_url(date(2026, 11, 7)) == DAY_URL
    assert mirage.day_url(date(2026, 1, 2)) == (
        "https://www.mirage.ru/spb/schedule/02.01.2026/"
    )


def test_fetch_requests_one_page_per_day_with_labels():
    class FakeHttp:
        def __init__(self):
            self.calls = []

        def get(self, url, *, venue, label):
            self.calls.append((url, venue, label))
            return f"body:{label}"

    days = [date(2026, 11, 6), date(2026, 11, 7)]
    http = FakeHttp()
    assert mirage.fetch(http, days) == [
        ("2026-11-06", "body:2026-11-06"),
        ("2026-11-07", "body:2026-11-07"),
    ]
    assert http.calls == [
        (
            "https://www.mirage.ru/spb/schedule/06.11.2026/",
            "mirage", "2026-11-06",
        ),
        (DAY_URL, "mirage", "2026-11-07"),
    ]


def test_day_fixture_parses_308_branch_rows_with_ticket_ids_and_halls():
    items = _day_items()
    assert len(items) == 308
    assert len({s.source_id for s in items}) == 308
    assert Counter(s.hall for s in items) == {
        "1": 41,
        "4": 44,
        "3": 38,
        "2": 44,
        "5": 42,
        "6": 32,
        "7": 29,
        "10": 8,
        "9": 10,
        "11": 4,
        "8": 10,
        "Зал №8 1/2": 6,
    }
    for screening in items:
        assert screening.venue == "mirage"
        assert screening.day == date(2026, 11, 7)
        assert screening.start.tzinfo is MSK
        assert screening.source_url == DAY_URL
        assert UUID_RE.fullmatch(screening.source_id)
        assert screening.url == (
            f"https://www.mirage.ru/ticket_new/{screening.source_id}/"
        )
        assert screening.price_min is None
        assert screening.price_max is None
        assert screening.language is None
        assert screening.tags == ()


def test_first_three_fixture_sessions_preserve_document_order_and_facts():
    items = _day_items()
    expected = [
        (
            "11:00", "Сказка о потерянном времени", "1",
            {"genres": ["приключения", "детский"], "age": "6+", "film_id": 7622},
        ),
        (
            "11:10", "Плетеный муж", "4",
            {
                "genres": ["комедия", "фантастика", "мелодрама", "фэнтези"],
                "age": "18+",
                "film_id": 7618,
            },
        ),
        (
            "11:20", "Барашек Шон и чудище лохматое", "3",
            {
                "genres": ["комедия", "мультфильм", "семейный"],
                "age": "6+",
                "film_id": 7641,
            },
        ),
    ]
    for screening, (clock, title, hall, facts) in zip(items[:3], expected):
        assert screening.start.strftime("%H:%M") == clock
        assert screening.title == title
        assert screening.hall == hall
        assert {
            key: value for key, value in screening.extra.items()
            if key != "price_raw"
        } == facts
        assert UUID_RE.fullmatch(screening.source_id)


def test_fixture_price_raw_presence_absence_and_multivalue_text():
    items = _day_items()
    with_raw = [s for s in items if "price_raw" in s.extra]
    without_raw = [s for s in items if "price_raw" not in s.extra]
    assert len(with_raw) == 277
    assert len(without_raw) == 31
    values = {s.extra["price_raw"] for s in with_raw}
    assert {
        "30000₽", "40000₽", "55000₽", "450₽ 400₽ 2400₽ 3600₽",
    } <= values
    assert all(isinstance(value, str) and value for value in values)
    assert all(s.price_min is None and s.price_max is None for s in items)


def test_wrong_date_fixture_is_skipped_and_warns():
    raw = [("2026-11-07", _body(PREVIOUS_DAY))]
    assert mirage.parse(raw, WINDOW) == []
    assert mirage.warning(raw) == (
        "сайт отдал другую дату вместо 07.11 — расписания на эти дни ещё нет"
    )


def test_each_real_fixture_parses_under_its_own_date_without_warning():
    for label, filename in [
        ("2026-11-06", PREVIOUS_DAY),
        ("2026-11-07", DAY),
    ]:
        day = date.fromisoformat(label)
        raw = [(label, _body(filename))]
        assert mirage._active_tab_date(mirage._soup(raw[0][1])) == day
        items = mirage.parse(raw, [day])
        assert items
        assert all(s.day == day for s in items)
        assert mirage.warning(raw) is None
        if filename == DAY:
            assert len(items) == 308


def test_branch_selection_uses_id_before_position_or_name():
    body = _page(
        _branch(
            _session(title="Чужой филиал", ticket=OTHER_TICKET),
            name="НА БОЛЬШОМ", href="/spb/cinema/2/",
        ),
        _branch(
            _session(title="Нужный филиал"),
            name="Другое написание названия", href="/spb/cinema/1/",
        ),
    )
    items = _parse(body)
    assert len(items) == 1
    assert items[0].title == "Нужный филиал"
    assert items[0].source_id == TICKET


def test_branch_name_fallback_normalizes_case_and_spaces(caplog):
    body = _page(
        _branch(
            _session(title="Чужой филиал", ticket=OTHER_TICKET),
            name="ДРУГОЙ", href="/spb/cinema/2/",
        ),
        _branch(
            _session(title="По имени"),
            name="  на \n большом  ", href="/changed-branch-link/",
        ),
    )
    items = _parse(body)
    assert len(items) == 1
    assert items[0].title == "По имени"
    assert "branch found by name only" in caplog.text
    # Выбор по имени допустим для разбора, но потеря ссылки остаётся подозрительной.
    assert mirage.legit_empty(body) is False


def test_session_without_price_digits_keeps_raw_text_and_no_numeric_price():
    body = _page(_branch(
        _session(title="Текст вместо цены", price_raw="  Цена \n уточняется  "),
        href="/spb/cinema/1/",
    ))
    items = _parse(body)
    assert len(items) == 1
    assert items[0].extra["price_raw"] == "Цена уточняется"
    assert items[0].price_min is None and items[0].price_max is None

    for price_raw in (None, "", "   "):
        items = _parse(_page(_branch(_session(price_raw=price_raw))))
        assert len(items) == 1
        assert "price_raw" not in items[0].extra
        assert items[0].price_min is None and items[0].price_max is None


def test_non_2d_formats_become_tags_and_plain_formats_do_not():
    for fmt, tags in [
        ("3D", ("3D",)),
        ("IMAX", ("IMAX",)),
        ("  IMAX \n 3D  ", ("IMAX 3D",)),
        ("2D", ()),
        ("2d", ()),
        ("", ()),
    ]:
        items = _parse(_page(_branch(_session(fmt=fmt))))
        assert len(items) == 1
        assert items[0].tags == tags


def test_age_genres_film_id_and_fractional_hall_are_preserved():
    body = _page(_branch(_session(
        hall="Зал №8 1/2",
        genres=" драма, , комедия,\n фантастика ",
        age="  12+ ",
        film_id=7654,
        price_raw=None,
    )))
    items = _parse(body)
    assert len(items) == 1
    assert items[0].hall == "Зал №8 1/2"
    assert items[0].extra == {
        "genres": ["драма", "комедия", "фантастика"],
        "age": "12+",
        "film_id": 7654,
    }

    items = _parse(_page(_branch(_session(
        hall="Зал №2", genres="", age="", film_id=None, price_raw=None,
    ))))
    assert len(items) == 1
    assert items[0].hall == "2"
    assert items[0].extra == {}


def test_legit_empty_when_our_branch_is_absent():
    body = _page(_branch(
        _session(title="Только другой филиал"),
        name="ДРУГОЙ", href="/spb/cinema/2/",
    ))
    assert _parse(body) == []
    assert mirage.legit_empty(body) is True


def test_legit_empty_our_empty_branch_requires_other_branches_empty_too():
    empty_day = _page(
        _branch(),
        _branch(name="ДРУГОЙ", href="/spb/cinema/2/"),
    )
    assert _parse(empty_day) == []
    assert mirage.legit_empty(empty_day) is True
    assert mirage.legit_empty(_page(_branch())) is True

    other_busy = _page(
        _branch(),
        _branch(
            _session(title="Чужой сеанс"),
            name="ДРУГОЙ", href="/spb/cinema/2/",
        ),
    )
    assert _parse(other_busy) == []
    assert mirage.legit_empty(other_busy) is False


def test_legit_empty_date_tab_shell_but_not_unlinked_blocks():
    shell = _page()
    assert _parse(shell) == []
    assert mirage.legit_empty(shell) is True
    assert mirage.legit_empty("<html><body>Ошибка сервера</body></html>") is False
    assert mirage.legit_empty("") is False

    for href in (None, "/changed-branch-link/"):
        body = _page(_branch(href=href))
        assert _parse(body) == []
        assert mirage.legit_empty(body) is False

    # Даже при отсутствии нашего филиала потерявший ссылку чужой блок подозрителен.
    assert mirage.legit_empty(_page(
        _branch(name="ДРУГОЙ", href=None),
    )) is False
    assert mirage.legit_empty(_body(DAY)) is False


def test_broken_sessions_fallback_id_deduplication_and_window_filter():
    valid = _session(ticket=None, price_raw=None)
    body = _page(_branch(
        _session(title="", ticket=None)
        + _session(clock="не время", ticket=None)
        + _session(clock="25:00", ticket=None)
        + _session(clock="12:60", ticket=None)
        + valid
        + valid
    ))
    items = _parse(body)
    assert len(items) == 1
    screening = items[0]
    assert screening.start == datetime(2026, 11, 7, 12, 30, tzinfo=MSK)
    assert screening.source_id == synthetic_id(
        "mirage", screening.start, screening.title, "2",
    )
    assert screening.url is None

    raw = [("2026-11-07", body), ("2026-11-07", body)]
    assert mirage.parse(raw, WINDOW) == items
    assert mirage.parse(raw, [date(2026, 11, 8)]) == []
    assert mirage.parse([("not-a-date", body)], WINDOW) == []
    assert mirage.warning([("not-a-date", body)]) is None


def test_far_future_day_is_a_schedule_shell_with_silent_zero():
    # День за пределами ~5 опубликованных вкладок: HTTP 200, настоящая страница
    # расписания (h1 «Расписание…», навигация с датами и премьерными ссылками),
    # но без активной вкладки, без сеансов и без распознаваемого блока филиала.
    # Парс молчит: 0 строк без warning. legit_empty остаётся строгим — форма
    # закладывает филиалы с потерянной ссылкой, что могло бы скрывать данные.
    # Ложной тревоги нет: правило «подозрительного нуля» работает на уровне
    # площадки, а первые дни окна всегда дают сеансы с опубликованных вкладок.
    raw = [("2026-11-12", _body("2026-11-12.html"))]
    assert mirage._active_tab_date(mirage._soup(raw[0][1])) is None
    assert mirage.parse(raw, [date(2026, 11, 12)]) == []
    assert mirage.warning(raw) is None
    assert mirage.legit_empty(raw[0][1]) is False
