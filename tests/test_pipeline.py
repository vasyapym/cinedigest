"""Конвейер: политика ошибок, перенос старых данных, правило нуля и запись на диск."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from cinedigest import pipeline
from cinedigest.http import Http
from cinedigest.model import MSK, Screening, Snapshot, VenueStatus

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=MSK)
WINDOW = [date(2026, 11, 5) + timedelta(days=offset) for offset in range(7)]  # 5–11 ноября

LEGIT_MARKER = '{"products": []}'


def _screening(venue: str, source_id: str, day: date, hour: int = 20, title: str = "Фильм") -> Screening:
    return Screening(
        venue=venue,
        source_id=source_id,
        title=title,
        start=datetime(day.year, day.month, day.day, hour, 0, tzinfo=MSK),
    )


class Venue:
    """Минимальный фейк адаптера: ID/NAME/DAILY + fetch/parse/legit_empty."""

    def __init__(self, venue_id: str, items=None, *, raw=None, daily=True, empty_marker=LEGIT_MARKER):
        self.ID = venue_id
        self.NAME = venue_id.upper()
        self.DAILY = daily
        self.items = items if items is not None else []
        self.raw = raw if raw is not None else [("page1", LEGIT_MARKER)]
        self.empty_marker = empty_marker

    def fetch(self, http, days):
        return [(label, http.get("https://fake.test/", venue=self.ID, label=label)) for label, _body in self.raw]

    def parse(self, raw, days):
        return self.items

    def legit_empty(self, body):
        return self.empty_marker is not None and body == self.empty_marker


class FakeHttp:
    """Мини-замена http.Http: считает запросы и капом отражает (venue, label) прогонов."""

    def __init__(self, fail_venue: str | None = None):
        self.request_count = 0
        self.calls: list[tuple[str, str]] = []
        self.sink = None
        self.fail_venue = fail_venue

    def get(self, url, params=None, headers=None, venue="", label=""):
        self.request_count += 1
        if venue == self.fail_venue:
            raise RuntimeError("boom")
        self.calls.append((venue, label))
        if self.sink is not None:
            self.sink(venue, label, LEGIT_MARKER)
        return LEGIT_MARKER


def _clock(*_a, **_k) -> datetime:
    return NOW


def test_success_path():
    venue = Venue("fakea", [_screening("fakea", "111", date(2026, 11, 6), 19),
                            _screening("fakea", "222", date(2026, 11, 7), 22)])
    other = Venue("fakeb", [_screening("fakeb", "333", date(2026, 11, 6), 21)])

    snapshot = pipeline.run([venue, other], http=FakeHttp(), clock=_clock)

    assert [s.venue for s in snapshot.statuses] == ["fakea", "fakeb"]
    for status in snapshot.statuses:
        assert status.ok is True
        assert status.error is None
        assert status.stale is False
        assert status.suspicious is False
        assert status.fetched_at == NOW
        assert status.requests == 1
    assert snapshot.statuses[0].count == 2
    assert snapshot.window_start == date(2026, 11, 5)
    assert snapshot.window_end == date(2026, 11, 11)
    assert [(s.venue, s.source_id) for s in snapshot.screenings] == [
        ("fakea", "111"), ("fakeb", "333"), ("fakea", "222"),
    ]  # хронология: 19:00 → 21:00 → 22:00


def test_out_of_window_screenings_are_filtered():
    venue = Venue("fakea", [_screening("fakea", "IN", WINDOW[1]),
                            _screening("fakea", "OUT", date(2026, 11, 19))])
    snapshot = pipeline.run([venue], http=FakeHttp(), clock=_clock)
    assert [s.source_id for s in snapshot.screenings] == ["IN"]


def test_fetch_failure_carries_previous_snapshot():
    carried = [_screening("fakea", "C1", date(2026, 11, 6)),
               _screening("fakea", "C2", date(2026, 11, 8)),
               _screening("fakea", "OLD", date(2026, 11, 12))]  # вне окна
    previous = Snapshot(
        generated_at=NOW - timedelta(days=1),
        window_start=date(2026, 11, 4),
        window_end=date(2026, 11, 10),
        statuses=[VenueStatus(venue="fakea", ok=True, count=3, fetched_at=NOW - timedelta(hours=24))],
        screenings=carried,
    )

    snapshot = pipeline.run([Venue("fakea")], previous=previous,
                            http=FakeHttp(fail_venue="fakea"), clock=_clock)

    status = snapshot.statuses[0]
    assert status.ok is False
    assert status.stale is True
    assert "fetch failed" in status.error and "RuntimeError" in status.error
    assert status.count == 2  # внеоконный OLD не переносится
    assert status.fetched_at == NOW - timedelta(hours=24)
    assert [s.source_id for s in snapshot.screenings] == ["C1", "C2"]


def test_stale_carry_over_expires_after_72h():
    previous = Snapshot(
        generated_at=NOW - timedelta(hours=73),
        window_start=date(2026, 10, 29),
        window_end=date(2026, 11, 4),
        statuses=[VenueStatus(venue="fakea", ok=True, count=1, fetched_at=NOW - timedelta(hours=73))],
        screenings=[_screening("fakea", "OLD", date(2026, 11, 6))],
    )

    snapshot = pipeline.run([Venue("fakea")], previous=previous,
                            http=FakeHttp(fail_venue="fakea"), clock=_clock)

    status = snapshot.statuses[0]
    assert status.ok is False
    assert status.stale is False
    assert status.count == 0
    assert status.fetched_at is None
    assert snapshot.screenings == []


def test_daily_venue_with_zero_rows_is_suspicious_and_carried_over():
    previous = Snapshot(
        generated_at=NOW - timedelta(hours=1),
        window_start=date(2026, 11, 5),
        window_end=date(2026, 11, 11),
        statuses=[VenueStatus(venue="fakea", ok=True, count=1, fetched_at=NOW - timedelta(hours=1))],
        screenings=[_screening("fakea", "PREV", date(2026, 11, 6))],
    )

    snapshot = pipeline.run([Venue("fakea", empty_marker=None)], previous=previous, http=FakeHttp(), clock=_clock)

    status = snapshot.statuses[0]
    assert status.suspicious is True          # DAILY-площадка отдала ноль без маркера «сеансов нет»
    assert "no screenings parsed" in status.error
    assert status.stale is True and status.count == 1
    assert status.fetched_at == NOW - timedelta(hours=1)
    assert [s.source_id for s in snapshot.screenings] == ["PREV"]


def test_not_daily_venue_with_zero_rows_is_just_ok():
    snapshot = pipeline.run([Venue("fakea", daily=False)], http=FakeHttp(), clock=_clock)

    status = snapshot.statuses[0]
    assert status.ok is True
    assert status.suspicious is False
    assert status.count == 0
    assert status.error is None


def test_doubled_source_id_within_venue_is_deduped():
    twin = _screening("fakea", "DUP", date(2026, 11, 6), 19)
    late_twin = _screening("fakea", "DUP", date(2026, 11, 6), 22)
    venue = Venue("fakea", [twin, late_twin], raw=[("page1", LEGIT_MARKER), ("page1b", LEGIT_MARKER)])

    snapshot = pipeline.run([venue], http=FakeHttp(), clock=_clock)

    assert [s.source_id for s in snapshot.screenings] == ["DUP"]  # дубль по (venue, source_id) схлопнут


def test_run_writes_docs_files(tmp_path):
    venue = Venue("fakea", [_screening("fakea", "111", date(2026, 11, 6))])

    snapshot = pipeline.run([venue], http=FakeHttp(), clock=_clock, out_dir=tmp_path)

    screenings_path = tmp_path / "docs" / "screenings.json"
    status_path = tmp_path / "docs" / "status.json"
    assert screenings_path.is_file() and status_path.is_file()

    data = json.loads(screenings_path.read_text(encoding="utf-8"))
    status_data = json.loads(status_path.read_text(encoding="utf-8"))
    assert isinstance(data["screenings"], list) and len(data["screenings"]) == 1
    assert isinstance(data["statuses"], list) and data["statuses"][0]["venue"] == "fakea"
    assert status_data == data["statuses"]
    assert data["window_start"] == "2026-11-05"
    assert json.loads(json.dumps(snapshot.to_json())) == data  # теги tuple «округляются» до list через json


class StubResponse:
    status_code = 200
    content = LEGIT_MARKER.encode("utf-8")

    def __init__(self):
        self.headers = {"Content-Type": "text/plain; charset=utf-8"}


class StubSession:
    def get(self, url, params=None, headers=None, timeout=None):
        return StubResponse()


def test_http_sink_receives_every_fetched_body():
    venue = Venue("fakea", raw=[("page1", LEGIT_MARKER), ("page2", LEGIT_MARKER)])
    collected: list[tuple[str, str]] = []
    sink = lambda venue_id, label, body: collected.append((venue_id, label))  # noqa: E731

    snapshot = pipeline.run([venue], http=FakeHttp(), clock=_clock, sink=sink)

    assert collected == [("fakea", "page1"), ("fakea", "page2")]
    assert snapshot.statuses[0].ok is True


def test_engine_sink_never_breaks_a_fetch():
    def broken_sink(venue_id, label, body):
        raise RuntimeError("archive is broken")

    http = Http(session=StubSession(), sink=broken_sink, sleep=lambda seconds: None,
                clock=lambda: 0.0, pause_seconds=0.0, retries=0)
    assert http.get("https://fake.test/", venue="fakea", label="page1") == LEGIT_MARKER  # ответ дошёл

    snapshot = pipeline.run([Venue("fakea")], http=http, clock=_clock, sink=broken_sink)
    assert snapshot.statuses[0].ok is True  # упавший архив не роняет прогон
