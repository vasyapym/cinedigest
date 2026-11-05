"""Модель v1.1: ночное правило, вечерняя отсечка, дедупликация и json-круговорот."""
from __future__ import annotations

import json
from datetime import date, datetime

from cinedigest.model import MSK, Screening, Snapshot, VenueStatus, dedupe, select


def _s(day: date, hour: int, minute: int, *, venue: str = "outcinema", source_id: str = "s1",
       title: str = "Фильм") -> Screening:
    return Screening(
        venue=venue,
        source_id=source_id,
        title=title,
        start=datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK),
    )


def test_night_show_belongs_to_previous_evening():
    show = _s(date(2026, 11, 6), 0, 30)  # 00:30 ночи с 6-го на 7-е — решение вечера 5-го
    assert show.digest_day == date(2026, 11, 5)
    assert show.is_evening is True


def test_late_evening_is_evening():
    show = _s(date(2026, 11, 6), 21, 30)
    assert show.digest_day == date(2026, 11, 6)
    assert show.is_evening is True


def test_afternoon_is_not_evening():
    assert _s(date(2026, 11, 6), 15, 0).is_evening is False


def test_select_grouping_evening_only():
    day = date(2026, 11, 6)
    evening = _s(day, 21, 30, source_id="evening")
    midnight = _s(date(2026, 11, 7), 0, 30, source_id="midnight")  # digest_day == 6-е
    daytime = _s(day, 15, 0, source_id="daytime")

    grouped = select([evening, midnight, daytime], [day], evening_only=True)
    assert grouped == {day: [evening, midnight]}

    grouped_all = select([evening, midnight, daytime], [day], evening_only=False)
    assert grouped_all == {day: [daytime, evening, midnight]}  # хронология: 15:00 < 21:30 < 00:30(+1)


def test_dedupe_keeps_first_occurrence_by_venue_and_source_id():
    day = date(2026, 11, 6)
    first = _s(day, 19, 0, venue="avrora", source_id="44", title="Новая")
    twin = _s(day, 21, 0, venue="avrora", source_id="44", title="Дубль")
    other_venue = _s(day, 20, 0, venue="poravkino", source_id="44", title="Другая площадка")

    kept = dedupe([first, twin, other_venue])
    assert [s.title for s in kept] == ["Новая", "Другая площадка"]


def test_screening_json_roundtrip_keeps_tags_as_tuple():
    original = Screening(
        venue="avrora",
        source_id="6ae99b",
        title="Плетёный муж",
        start=datetime(2026, 11, 6, 14, 20, tzinfo=MSK),
        hall="Большой",
        price_min=400,
        price_max=550,
        language=None,
        tags=("3D",),
        url="https://avrora.spb.ru/",
        source_url="https://kinokassa.kinoplan24.ru/api/v2/release/playbill?city_id=2&date=2026-11-06",
        extra={"release_id": 25872, "year": 2026, "genres": ["фантастика"]},
    )
    restored = Screening.from_json(json.loads(json.dumps(original.to_json())))
    assert restored == original
    assert isinstance(restored.tags, tuple)
    assert restored.tags == ("3D",)


def test_snapshot_json_roundtrip():
    day = date(2026, 11, 6)
    screening = _s(day, 22, 30, venue="poravkino", source_id="43886", title="Гарри Поттер и философский камень")
    status = VenueStatus(venue="poravkino", ok=True, count=1, fetched_at=datetime(2026, 11, 5, 12, 0, tzinfo=MSK))
    snapshot = Snapshot(
        generated_at=datetime(2026, 11, 5, 12, 0, tzinfo=MSK),
        window_start=date(2026, 11, 5),
        window_end=date(2026, 11, 11),
        statuses=[status],
        screenings=[screening],
    )
    restored = Snapshot.from_json(json.loads(json.dumps(snapshot.to_json())))
    assert restored.window_start == snapshot.window_start
    assert restored.window_end == snapshot.window_end
    assert restored.screenings == snapshot.screenings
    assert restored.statuses == snapshot.statuses
