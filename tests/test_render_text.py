"""Текстовый рендер: булавки принятых примеров, суточные блоки, статусы, разбивка Telegram.

Проверка календаря: в примерах дизайн-документа 2026-11-05 назван средой («ср»), но в
реальном календаре это четверг — булавки ниже закрепляют РЕАЛЬНЫЕ названия дней (WD
считается по той же API, что и рендер).
"""
from __future__ import annotations

from datetime import date, datetime

from cinedigest.model import MSK, Screening, VenueStatus
from cinedigest.render_text import (
    TG_LIMIT,
    day_block,
    day_long,
    heading,
    is_clean,
    plural,
    render_digest,
    render_telegram,
    split_telegram,
    statuses_compact,
    status_line,
    row,
    hall,
    lang,
    price,
)

THU_NIGHT = datetime(2026, 11, 12, 0, 30, tzinfo=MSK)  # четверг 00:30 → бейдж «ночь на чт»


def _screening(**fields) -> Screening:
    base = dict(
        venue="domkino",
        source_id="s1",
        title="Фильм",
        start=datetime(2026, 11, 5, 19, 0, tzinfo=MSK),
    )
    base.update(fields)
    return Screening(**base)


def test_plural_pins():
    assert plural(1, "сеанс", "сеанса", "сеансов") == "1 сеанс"
    assert plural(2, "сеанс", "сеанса", "сеансов") == "2 сеанса"
    assert plural(5, "сеанс", "сеанса", "сеансов") == "5 сеансов"
    assert plural(11, "сеанс", "сеанса", "сеансов") == "11 сеансов"
    assert plural(21, "сеанс", "сеанса", "сеансов") == "21 сеанс"
    assert plural(23, "сеанс", "сеанса", "сеансов") == "23 сеанса"
    assert plural(None, "место", "места", "мест") == "0 мест"


def test_day_long_and_heading_pins():
    assert day_long(date(2026, 11, 5)) == "чт 5 ноября"
    assert heading(date(2026, 11, 5), date(2026, 11, 5)) == "СЕГОДНЯ · чт 5 ноября"
    assert heading(date(2026, 11, 6), date(2026, 11, 5)) == "ЗАВТРА · пт 6 ноября"
    assert heading(date(2026, 11, 7), date(2026, 11, 5)) == "СБ 7 НОЯБРЯ"


def test_lang_folds_sub_from_language_and_from_tags():
    assert lang(_screening(language="SUB")) == "субтитры"          # язык-константа
    assert lang(_screening(tags=("SUB",))) == "субтитры"           # kinoplan-псевдоформат в тегах
    assert lang(_screening(language="Дублирование")) == "дублирование"
    big = "Английский язык, русские субтитры"
    assert lang(_screening(language=big)) == "английский язык, русские субтитры"  # строчная первая
    assert lang(_screening()) == ""


def test_price_pins():
    assert price(_screening(price_min=400, price_max=550)) == "400–550 ₽"
    assert price(_screening(price_min=350, price_max=350)) == "350 ₽"
    assert price(_screening(price_min=None, price_max=550)) == "до 550 ₽"
    assert price(_screening()) == ""


def test_hall_pins():
    assert hall("2") == "зал 2"
    assert hall("Большой зал") == "Большой зал"
    assert hall("Белый зал") == "Белый зал"


def test_row_adopted_example_sabrina():
    sabrina = _screening(
        title="Сабрина",
        hall="Белый зал",
        language="SUB",
        price_min=350,
        price_max=350,
        extra={"year": 1954, "duration_min": 113, "age": "12+"},
    )
    assert row(sabrina) == "19:00 · Дом кино · Сабрина (1954) · 113 мин · 12+ · субтитры · Белый зал · 350 ₽"


def test_row_adopted_example_dune_and_kinonoch_night_badge():
    dune = _screening(
        venue="avrora",
        title="Дюна",
        source_id="s2",
        start=datetime(2026, 11, 5, 19, 30, tzinfo=MSK),
        hall="Большой",
        language="Дублирование",
        price_min=400,
        price_max=550,
        tags=("3D",),
        extra={"year": 2021},
    )
    assert row(dune) == "19:30 · Аврора · Дюна (2021) · дублирование · Большой · 400–550 ₽ · [3D]"

    kinonoch = _screening(
        venue="outcinema",
        title="Киноночь: нуар",
        source_id="s3",
        start=THU_NIGHT,
        price_min=600,
        price_max=600,
        tags=("киноночь",),
        extra={"year": 1944},
    )
    assert row(kinonoch) == "00:30 · Out Cinema · Киноночь: нуар (1944) · 600 ₽ · [киноночь] · ночь на чт"


def test_day_block_empty_evening_with_daytime():
    daytime = _screening(start=datetime(2026, 11, 6, 14, 0, tzinfo=MSK))
    lines = day_block(date(2026, 11, 6), [daytime], date(2026, 11, 5), evening=[], underline=True)
    head = "ЗАВТРА · пт 6 ноября"
    assert lines == [head, "-" * len(head), "— вечером сеансов нет (днём: 1)"]


def test_status_line_pins():
    now = datetime(2026, 11, 5, 9, 1, tzinfo=MSK)
    clean = VenueStatus(venue="domkino", ok=True, count=14, fetched_at=now, requests=3, seconds=1.2)
    assert status_line(clean) == "✓ Дом кино — 14 сеансов · 05.11 09:01 · 3 запр., 1.2 с"

    stale = VenueStatus(venue="rodina", ok=False, count=9, fetched_at=datetime(2026, 11, 4, 9, 0, tzinfo=MSK),
                        stale=True, error="timeout")
    assert status_line(stale) == (
        "⚠ Родина — 9 сеансов · 04.11 09:00 · данные с прошлого запуска · ошибка: timeout"
    )

    suspicious = VenueStatus(venue="avrora", ok=True, count=0, fetched_at=now, suspicious=True)
    assert status_line(suspicious) == (
        "⚠ Аврора — 0 сеансов · 05.11 09:01 · ноль без пометки «сеансов нет» — подозрительно"
    )

    dead = VenueStatus(venue="outcinema", ok=False, count=0, fetched_at=None, error="HTTP 503")
    assert status_line(dead) == "✗ Out Cinema — 0 сеансов · ошибка: HTTP 503"

    assert is_clean(clean) is True
    assert is_clean(stale) is False
    assert is_clean(suspicious) is False
    assert is_clean(dead) is False


def test_statuses_compact_collapses_clean_venues_into_one_line():
    now = datetime(2026, 11, 5, 9, 1, tzinfo=MSK)
    first = VenueStatus(venue="domkino", ok=True, count=14, fetched_at=now)
    second = VenueStatus(venue="poravkino", ok=True, count=11, fetched_at=now)
    third = VenueStatus(venue="lenfilm", ok=True, count=6, fetched_at=now)
    dead = VenueStatus(venue="outcinema", ok=False, count=0, fetched_at=None, error="HTTP 503")
    assert statuses_compact([first, second, third, dead]) == [
        "✓ Дом кино 14 · Художественный 11 · Ленфильм 6",
        "✗ Out Cinema — 0 сеансов · ошибка: HTTP 503",
    ]


def test_render_digest_adopted_example_shape():
    today = date(2026, 11, 5)
    sabrina = _screening(title="Сабрина", price_min=350, price_max=350, language="SUB",
                         extra={"year": 1954})
    evening = [sabrina]
    days = [(today, [sabrina]), (date(2026, 11, 6), [])]
    statuses = [
        VenueStatus(venue="domkino", ok=True, count=1, fetched_at=datetime(2026, 11, 5, 9, 1, tzinfo=MSK)),
    ]
    generated = datetime(2026, 11, 5, 9, 1, tzinfo=MSK)

    digest = render_digest(days, evening, statuses, generated, today)

    lines = digest.splitlines()
    assert lines[0] == "КИНО ВЕЧЕРОМ · СПб · собрано чт 5 ноября 09:01"
    assert lines[1] == ""
    assert lines[2] == "СЕГОДНЯ · чт 5 ноября"
    assert lines[3] == "-" * len(lines[2])  # подчёркивание по ширине заголовка
    assert lines[4] == "19:00 · Дом кино · Сабрина (1954) · субтитры · 350 ₽"
    assert "ЗАВТРА · пт 6 ноября" in lines
    assert "— вечером сеансов нет" in lines
    assert "ИСТОЧНИКИ" in lines
    assert "---------" in lines
    assert "✓ Дом кино — 1 сеанс · 05.11 09:01" in lines
    assert digest.endswith("\n")


def test_render_telegram_adopted_example():
    today = date(2026, 11, 5)
    sabrina = _screening(title="Сабрина", price_min=350, price_max=350, language="SUB",
                         extra={"year": 1954})
    tomorrow_evening = _screening(title="Завтрашний", source_id="z1",
                                  start=datetime(2026, 11, 6, 19, 0, tzinfo=MSK))
    tomorrow_morning = _screening(title="Дневной", source_id="z2",
                                  start=datetime(2026, 11, 6, 10, 0, tzinfo=MSK))
    evening = [sabrina, tomorrow_evening]
    days = [
        (today, [sabrina]),
        (date(2026, 11, 6), [tomorrow_evening, tomorrow_morning]),
    ]
    statuses = [
        VenueStatus(venue="domkino", ok=True, count=2, fetched_at=datetime(2026, 11, 5, 9, 1, tzinfo=MSK)),
        VenueStatus(venue="rodina", ok=False, count=9, fetched_at=datetime(2026, 11, 4, 9, 0, tzinfo=MSK),
                    stale=True, error="timeout"),
    ]
    generated = datetime(2026, 11, 5, 9, 1, tzinfo=MSK)

    text = render_telegram(days, evening, statuses, generated, today)
    assert text.splitlines()[:2] == [
        "СЕГОДНЯ ВЕЧЕРОМ · чт 5 ноября",
        "19:00 · Дом кино · Сабрина (1954) · субтитры · 350 ₽",
    ]
    assert "Завтра вечером: 1 сеанс" in text
    assert "✓ Дом кино 2" in text
    assert "⚠ Родина — 9 сеансов · 04.11 09:00 · данные с прошлого запуска · ошибка: timeout" in text
    assert "собрано 09:01" in text
    assert "https://" not in text  # page_url опционален

    with_url = render_telegram(days, evening, statuses, generated, today, page_url="https://p.test/")
    assert with_url.endswith("https://p.test/")


def test_split_telegram_small_text_is_one_part():
    text = "СЕГОДНЯ ВЕЧЕРОМ\n19:00 · Дом кино · Сабрина"
    assert split_telegram(text) == [text]


def test_split_telegram_prefers_blank_line_boundary():
    first = "а" * 4000
    second = "б" * 4000
    parts = split_telegram(f"{first}\n\n{second}")
    assert parts == [f"(1/2)\n{first}", f"(2/2)\n{second}"]
    assert all(len(p) <= TG_LIMIT for p in parts)


def test_split_telegram_falls_back_to_line_end():
    first = "а" * 4000
    second = "б" * 4000
    parts = split_telegram(f"{first}\n{second}")  # пустой строки нет
    assert len(parts) == 2
    assert parts[0] == f"(1/2)\n{first}"      # разрез по концу строки, не внутри слова
    assert parts[1] == f"(2/2)\n{second}"
    assert all(len(p) <= TG_LIMIT for p in parts)


def test_split_telegram_hard_cuts_inside_an_overlong_line():
    parts = split_telegram("а" * 9000)
    assert len(parts) == 3
    assert all(len(p) <= TG_LIMIT for p in parts)
    assert all(p.split("\n", 1)[1] == "а" * (TG_LIMIT - 8) for p in parts[:2])
    joined = "".join(p.split("\n", 1)[1] for p in parts)
    assert joined == "а" * 9000  # части, склеенные без заголовков, ровно исходный текст
