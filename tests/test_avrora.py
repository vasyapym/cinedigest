"""Аврора: разбор плея списка Kinoplan и свои маркеры «сеансов нет»."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK
from cinedigest.venues import avrora

FIXTURES = Path(__file__).parent / "fixtures" / "avrora"
DAY = date(2026, 11, 6)
DAY_LABEL = "2026-11-06"

# Пины сняты с сохранённого плея 2026-11-06 (короткая проверка: id, тайтл, время, зал, цена).
EXPECTED = [
    ("6ae99b733f0000a9009e80d9", "Плетёный муж", (14, 20), "Большой", (400, 550)),
    ("6ae99b193f0000bd00083944", "Плетёный муж", (21, 50), "Большой", (550, 700)),
    ("6ae99b323f00004f000839c8", "Отверженные", (11, 0), "Большой", (350, 500)),
    ("6ae99c263f0000a8009e82b2", "Рождение империи", (15, 40), "Малый", (450, 450)),
    ("6ae99b243c0000ab00567891", "Рождение империи", (19, 10), "Большой", (550, 700)),
    ("6ae99b5b3f00004b009e80b7", "Битва моторов", (16, 25), "Большой", (450, 600)),
    ("6ae99b873f00004d00083a1a", "Романовы: преданность и предательство", (13, 20), "Малый", (400, 400)),
    ("6ae99c9d3f000048009e8357", "Любовь моя", (21, 10), "Малый", (550, 550)),
    ("6ae99c5d3f0000ae00083f20", "Фьорд (версия с субтитрами)", (18, 20), "Малый", (550, 550)),
]


def _day_raw() -> list[tuple[str, str]]:
    body = (FIXTURES / f"{DAY_LABEL}.json").read_text(encoding="utf-8")
    return [("shell", "<html>shell заглушка — parse обязан её игнорировать</html>"), (DAY_LABEL, body)]


def test_november_6_yields_nine_pinned_screenings():
    items = avrora.parse(_day_raw(), [DAY])

    assert len(items) == 9
    for screening, (source_id, title, (hour, minute), hall, (low, high)) in zip(items, EXPECTED):
        assert screening.source_id == source_id
        assert screening.title == title
        assert screening.start == datetime(2026, 11, 6, hour, minute, tzinfo=MSK)
        assert screening.hall == hall
        assert (screening.price_min, screening.price_max) == (low, high)


def test_first_fixture_seance_carries_release_and_kopeck_prices():
    items = avrora.parse(_day_raw(), [DAY])
    male = items[0]
    assert male.extra["release_id"] == 25872  # «Плетёный муж»
    assert (male.price_min, male.price_max) == (400, 550)  # 40000/55000 копеек → 400/550


def test_hall_titles_and_language_wording():
    items = avrora.parse(_day_raw(), [DAY])
    by_id = {s.source_id: s for s in items}

    assert by_id["6ae99b193f0000bd00083944"].tags == ("SUB",)  # формат не-2D → бейдж
    assert by_id["6ae99c9d3f000048009e8357"].language == "Русский"  # release voiceovers
    assert by_id["6ae99b733f0000a9009e80d9"].language is None
    assert all(s.venue == "avrora" for s in items)


def test_seance_in_another_cinema_is_skipped():
    data = json.loads((FIXTURES / f"{DAY_LABEL}.json").read_text(encoding="utf-8"))
    release = next(r for r in data["releases"] if r.get("id") == 25872)
    for seance in release["seances"]:
        seance["cinema_id"] = 71  # чужой кинотеатр сети
        break

    items = avrora.parse([(DAY_LABEL, json.dumps(data, ensure_ascii=False))], [DAY])
    assert "6ae99b733f0000a9009e80d9" not in {s.source_id for s in items}


def test_resolve_settings_from_shell_and_fallbacks():
    shell = (
        '<html>a kinokassaApiUrl="https://api.kinoplan24.ru/" b '
        'kinositeSettings={token:"abc123XYZ"}</html>'
    )
    assert avrora.resolve_settings(shell) == ("https://api.kinoplan24.ru", "abc123XYZ")

    api, token = avrora.resolve_settings("")
    assert api == config.AVRORA_API_FALLBACK
    assert token == config.AVRORA_TOKEN_FALLBACK


def test_legit_empty_shapes():
    empty_day = json.dumps({"releases": [{"id": 1, "seances": []}, {"id": 2, "seances": []}]})
    assert avrora.legit_empty(empty_day) is True

    with_seance = json.dumps({"releases": [{"id": 1, "seances": [{"id": "s1"}]}]})
    assert avrora.legit_empty(with_seance) is False

    assert avrora.legit_empty("{[]}") is False  # не плея — не «легитимно пусто»
    assert avrora.legit_empty("[]") is False


def test_shell_label_is_ignored_by_parse():
    # fetch() требует сети и не тестируется; здесь проверен только контракт метки shell.
    raw = _day_raw()
    assert [label for label, _body in raw] == ["shell", DAY_LABEL]
    assert len(avrora.parse(raw, [DAY])) == 9
