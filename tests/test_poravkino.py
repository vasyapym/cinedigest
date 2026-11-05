"""Художественный: разбор сохранённых расписаний и свои маркеры «сеансов нет»."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK
from cinedigest.venues import poravkino

FIXTURES = Path(__file__).parent / "fixtures" / "poravkino"


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_november_6_yields_two_pinned_screenings():
    raw = [("2026-11-06", _body("2026-11-06.json"))]
    days = [date(2026, 11, 6)]
    items = poravkino.parse(raw, days)

    assert [(s.source_id, s.title) for s in items] == [
        ("43886", "Гарри Поттер и философский камень"),
        ("43779", "Лиля"),
    ]
    potter = items[0]
    assert potter.start == datetime(2026, 11, 6, 22, 30, tzinfo=MSK)  # 19:30 UTC → 22:30 MSK
    assert potter.hall == "2"
    assert (potter.price_min, potter.price_max) == (500, 500)
    assert potter.hall == "2" and potter.start.tzname() == "MSK"

    lilya = items[1]
    assert lilya.start == datetime(2026, 11, 6, 22, 0, tzinfo=MSK)  # 19:00 UTC → 22:00 MSK
    assert lilya.hall == "Премьер"
    assert (lilya.price_min, lilya.price_max) == (500, 500)
    assert (lilya.tags, lilya.language) == ((), None)
    assert lilya.url == config.PORAVKINO_SITE_URL
    assert lilya.source_url == f"{config.PORAVKINO_SCHEDULE_URL}?date=2026-11-06"


def test_november_7_yields_one_pinned_screening():
    raw = [("2026-11-07", _body("2026-11-07.json"))]
    days = [date(2026, 11, 7)]
    items = poravkino.parse(raw, days)

    assert [(s.source_id, s.title, s.hall, s.start, s.price_min) for s in items] == [
        ("43887", "Гарри Поттер и философский камень", "2", datetime(2026, 11, 7, 22, 30, tzinfo=MSK), 500)
    ]


def test_union_of_two_days_has_three_unique_screenings():
    raw = [
        ("2026-11-06", _body("2026-11-06.json")),
        ("2026-11-07", _body("2026-11-07.json")),
    ]
    days = [date(2026, 11, 6), date(2026, 11, 7)]
    items = poravkino.parse(raw, days)
    ids = [s.source_id for s in items]
    assert len(items) == 3
    assert len(set(ids)) == len(ids)


def test_legit_empty_shapes():
    assert poravkino.legit_empty("[]") is True
    assert poravkino.legit_empty(json.dumps([{"id": 1, "name": "X", "performances": []}])) is True
    assert poravkino.legit_empty(json.dumps([{"id": 1, "name": "X", "performances": None}])) is False


def test_wrong_date_error_is_not_a_legitimate_empty():
    body = _body("no-date.json")
    assert json.loads(body) == {"error": "wrong date"}  # фиксатор формы ответа
    assert poravkino.legit_empty(body) is False
