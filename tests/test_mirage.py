"""Мираж на Большом: веточная страница-расписание (/spb/schedule/{день}/cinema/1/), выбор филиала, дата, билеты и формы пустого дня."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK, synthetic_id
from cinedigest.venues import mirage

FIXTURES = Path(__file__).parent / "fixtures" / "mirage"
DAY = "2026-11-06.html"
PREVIOUS_DAY = "2026-11-05.html"
EVEN_LATER_DAY = "2026-11-07.html"
FAR_DAY = "2026-11-12.html"
DAY_URL = "https://www.mirage.ru/spb/schedule/06.11.2026/cinema/1/"
WINDOW = [date(2026, 11, 6)]
TICKET = "00000000-0000-4000-8000-000000000001"
OTHER_TICKET = "00000000-0000-4000-8000-000000000002"
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# Залы настоящей ветки 1 (Большой пр. П.С.): №1…№7; 9–11 и «№8 1/2» живут у других веток,
# и городская страница (где все ветки сливаются в один .session-box) подмешивала их к нам.
BRANCH1_HALLS = {"1", "2", "3", "4", "5", "6", "7"}


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _parse(body: str, label: str = "2026-11-06"):
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


def _page(*boxes: str, active: str = "06.11.2026") -> str:
    return (
        "<html><body>"
        f'<a class="date-tab active" href="/spb/schedule/{active}/">{active}</a>'
        + "".join(boxes)
        + "</body></html>"
    )


def test_day_url_pattern():
    assert mirage.day_url(date(2026, 11, 6)) == DAY_URL
    assert mirage.day_url(date(2026, 1, 2)) == (
        "https://www.mirage.ru/spb/schedule/02.01.2026/cinema/1/"
    )


def test_fetch_requests_one_page_per_day_with_labels():
    class FakeHttp:
        def __init__(self):
            self.calls = []

        def get(self, url, *, venue, label):
            self.calls.append((url, venue, label))
            return f"body:{label}"

    days = [date(2026, 11, 5), date(2026, 11, 6)]
    http = FakeHttp()
    assert mirage.fetch(http, days) == [
        ("2026-11-05", "body:2026-11-05"),
        ("2026-11-06", "body:2026-11-06"),
    ]
    assert http.calls == [
        (
            "https://www.mirage.ru/spb/schedule/05.11.2026/cinema/1/",
            "mirage", "2026-11-05",
        ),
        (DAY_URL, "mirage", "2026-11-06"),
    ]


def test_day_fixture_parses_36_branch_rows_with_ticket_ids_and_halls():
    items = _day_items()
    assert len(items) == 36
    assert len({s.source_id for s in items}) == 36
    assert Counter(s.hall for s in items) == {
        "3": 6,
        "4": 6,
        "1": 5,
        "2": 5,
        "6": 5,
        "7": 5,
        "5": 4,
    }
    for screening in items:
        assert screening.venue == "mirage"
        assert screening.day == date(2026, 11, 6)
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
    # Защита от смешивания веток: у ветки 1 нет залов №8 1/2 и №9–11, они жили у других
    # веток и городская страница подмешивала их в один .session-box (инцидент 2026-11-05).
    assert {s.hall for s in items} <= BRANCH1_HALLS


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
    values = {s.extra["price_raw"] for s in with_raw}
    assert len(with_raw) == 5
    assert {"30000₽", "40000₽", "55000₽"} <= values
    assert all(isinstance(value, str) and value for value in values)
    assert all(s.price_min is None and s.price_max is None for s in items)

    # 05.11 несёт многоитарифную строку цен в одном сеансе — она хранится дословно
    # (окно этого теста — 06.11, поэтому парсим тело 05.11 под его собственным днём).
    earlier = mirage.parse([("2026-11-05", _body(PREVIOUS_DAY))], [date(2026, 11, 5)])
    raw05 = [s.extra["price_raw"] for s in earlier if "price_raw" in s.extra]
    assert "500₽ 550₽ 1700₽ 2550₽" in raw05


def test_wrong_date_fixture_is_skipped_and_warns():
    raw = [("2026-11-06", _body(PREVIOUS_DAY))]
    assert mirage.parse(raw, WINDOW) == []
    assert mirage.warning(raw) == (
        "сайт отдал другую дату вместо 06.11 — расписания на эти дни ещё нет"
    )


def test_each_real_fixture_parses_under_its_own_date_without_warning():
    for label, filename, expected in [
        ("2026-11-05", PREVIOUS_DAY, 29),
        ("2026-11-06", DAY, 36),
        ("2026-11-07", EVEN_LATER_DAY, 36),
    ]:
        day = date.fromisoformat(label)
        raw = [(label, _body(filename))]
        assert mirage._active_tab_date(mirage._soup(raw[0][1])) == day
        items = mirage.parse(raw, [day])
        assert len(items) == expected
        assert all(s.day == day for s in items)
        assert {s.hall for s in items} <= BRANCH1_HALLS
        assert mirage.warning(raw) is None


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
    assert screening.start == datetime(2026, 11, 6, 12, 30, tzinfo=MSK)
    assert screening.source_id == synthetic_id(
        "mirage", screening.start, screening.title, "2",
    )
    assert screening.url is None

    raw = [("2026-11-06", body), ("2026-11-06", body)]
    assert mirage.parse(raw, WINDOW) == items
    assert mirage.parse(raw, [date(2026, 11, 8)]) == []
    assert mirage.parse([("not-a-date", body)], WINDOW) == []
    assert mirage.warning([("not-a-date", body)]) is None


def test_far_future_day_is_a_schedule_shell_with_silent_zero():
    # День за пределами ~5 опубликованных вкладок: HTTP 200, настоящая страница
    # расписания, но без активной вкладки, без сеансов и без блока филиала.
    # Парс молчит: 0 строк без warning; legit_empty остаётся строгим. Ложной
    # тревоги нет: правило «подозрительного нуля» работает на уровне площадки,
    # а первые дни окна дают сеансы с опубликованных вкладок.
    raw = [("2026-11-12", _body(FAR_DAY))]
    assert mirage._active_tab_date(mirage._soup(raw[0][1])) is None
    assert mirage.parse(raw, [date(2026, 11, 12)]) == []
    assert mirage.warning(raw) is None
    assert mirage.legit_empty(raw[0][1]) is False
