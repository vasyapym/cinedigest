"""Кинокасса: общий разбортор плея Kinoplan, проверен на авроровском фиксе."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK
from cinedigest.venues import kinokassa

FIXTURES = Path(__file__).parent / "fixtures" / "avrora"
DAY = date(2026, 11, 6)
DAY_LABEL = "2026-11-06"
SOURCE_URL = (
    f"{config.AVRORA_API_FALLBACK}/api/v2/release/playbill"
    f"?city_id={config.AVRORA_CITY_ID}&date={DAY_LABEL}"
)

# Пины те же, что в test_avrora: 9 сеансов фида 2026-11-06, сняты по порядку файла.
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


def _body() -> dict:
    return json.loads((FIXTURES / f"{DAY_LABEL}.json").read_text(encoding="utf-8"))


def _parse(data: dict, days=(DAY,)) -> list:
    return kinokassa.parse_playbill(
        data,
        list(days),
        cinema_id=config.AVRORA_CINEMA_ID,
        venue="avrora",
        url=config.AVRORA_SITE_URL,
        source_url=SOURCE_URL,
        label=DAY_LABEL,
    )


def test_avrora_fixture_holds_nine_pinned_screenings_through_the_shared_module():
    items = _parse(_body())

    assert len(items) == 9
    for screening, (source_id, title, (hour, minute), hall, (low, high)) in zip(items, EXPECTED):
        assert screening.source_id == source_id
        assert screening.title == title
        assert screening.start == datetime(2026, 11, 6, hour, minute, tzinfo=MSK)
        assert screening.hall == hall
        assert (screening.price_min, screening.price_max) == (low, high)
        assert screening.venue == "avrora"
        assert screening.url == config.AVRORA_SITE_URL
        assert screening.source_url == SOURCE_URL


def test_seance_of_a_foreign_cinema_id_is_skipped():
    data = _body()
    release = next(r for r in data["releases"] if r.get("id") == 25872)
    for seance in release["seances"]:
        seance["cinema_id"] = 999  # чужой кинотеатр сети
        break

    items = _parse(data)
    assert len(items) == 8
    assert "6ae99b733f0000a9009e80d9" not in {s.source_id for s in items}


def test_screenings_outside_the_window_days_are_dropped():
    items = _parse(_body(), days=(date(2026, 11, 7),))

    assert items == []


def test_playbill_without_a_releases_list_raises():
    for broken in ([], {"releases": {}}, {"no_releases": []}):
        try:
            _parse(broken)
        except ValueError as exc:
            assert "playbill without a 'releases' list" in str(exc)
        else:
            raise AssertionError(f"{broken!r} must raise a releases error")


def test_dedupe_by_source_id_keeps_first_occurrence_in_file_order():
    first = _parse(_body())
    second = _parse(_body())

    deduped = kinokassa.dedupe_by_source_id(first + second)

    assert [s.source_id for s in deduped] == [expected[0] for expected in EXPECTED]
    assert len(deduped) == 9


def test_language_wording_and_lookup_tables():
    table = kinokassa.lookup([
        {"id": 3, "title": "Русский"},
        {"id": 4, "name": "Английский"},
    ])
    assert table == {"3": "Русский", "4": "Английский"}
    assert kinokassa.lookup(["premiere", "for_kids"]) == {}  # строки-квалификаторы пропускаются

    assert kinokassa.wording(3, table) == "Русский"  # id значения против таблицы
    assert kinokassa.wording({"title": "Дубляж"}, table) == "Дубляж"  # уже-словарь
    assert kinokassa.wording(False, table) is None  # отсутствие — не значение
    assert kinokassa.wording(None, table) is None
    assert kinokassa.resolve_all([3, {"title": "Японский"}, 999], table) == ["Русский", "Японский"]


def test_release_level_language_formats_and_prices():
    release = {
        "id": 55,
        "title": "Тестовый фильм",
        "year": 1989,
        "duration": 90,
        "age_rating": "12+",
        "genres": [{"title": "драма"}],
        "countries": [{"title": "США"}],
        "subtitles": [],
        "voiceovers": [{"title": "Русский"}],
        "seances": [{
            "id": "s1",
            "cinema_id": config.AVRORA_CINEMA_ID,
            "start_date_time": "2026-11-06T21:50:00+03:00",
            "hall": {"title": "Большой"},
            "price": {"min": 40000, "max": 45000},
            "free_places_count": 5,
            "is_allowed_online_sale": True,
            "formats": [{"title": "2D"}, {"title": "IMAX"}],
            "subtitles": None,
            "voiceover": None,
        }],
    }
    items = _parse({"releases": [release]})

    assert len(items) == 1
    screening = items[0]
    assert (screening.price_min, screening.price_max) == (400, 450)  # копейки → рубли
    assert screening.language == "Русский"  # релиз-уровень: voiceovers-список
    assert screening.tags == ("IMAX",)  # не-2D формат → бейдж
    assert screening.extra == {
        "release_id": 55,
        "year": 1989,
        "duration_min": 90,
        "age": "12+",
        "genres": ["драма"],
        "country": "США",
        "free_places": 5,
        "online_sale": True,
    }


def test_empty_playbill_shapes():
    assert kinokassa.empty_playbill(json.dumps({"releases": [{"id": 1, "seances": []}]})) is True
    assert kinokassa.empty_playbill(json.dumps({"releases": [{"id": 1, "seances": [{"id": "s1"}]}]})) is False
    assert kinokassa.empty_playbill("{[]}") is False
    assert kinokassa.empty_playbill("[]") is False
