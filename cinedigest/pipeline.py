"""One-window pipeline: per-venue fetch+parse, failure policy, stale carry-over, suspicious-zero rule, snapshot."""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import config
from .http import Http, Sink, file_sink
from .model import MSK, Screening, Snapshot, VenueStatus, dedupe

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def now_msk() -> datetime:
    return datetime.now(MSK)


def today_msk() -> date:
    return now_msk().date()


def window(today: date, days: int = config.WINDOW_DAYS) -> list[date]:
    return [today + timedelta(days=i) for i in range(days)]


def run_id(generated_at: datetime) -> str:
    return generated_at.astimezone(MSK).strftime(config.RUN_ID_FORMAT)


def run(
    venues: list,
    *,
    previous: Snapshot | None = None,
    http=None,
    out_dir: Path | str | None = None,
    clock: Clock = now_msk,
    sink: Sink | None = None,
) -> Snapshot:
    """Fetch every venue sequentially for the current window and assemble a Snapshot.

    `sink` overrides the raw-body archive (tests); otherwise an output directory wires a
    file sink under <out_dir>/snapshots/<run-id>/ and the snapshot is written to <out_dir>/docs/.
    """
    generated_at = clock().astimezone(MSK)
    days = window(generated_at.date())
    if http is None:
        http = Http()
    if sink is not None:
        http.sink = sink
    elif out_dir is not None:
        http.sink = file_sink(Path(out_dir) / config.SNAPSHOTS_DIRNAME / run_id(generated_at))

    statuses: list[VenueStatus] = []
    screenings: list[Screening] = []
    for venue in venues:
        status, items = run_venue(venue, http, days, previous=previous, clock=clock)
        statuses.append(status)
        screenings.extend(items)

    snapshot = Snapshot(
        generated_at=generated_at,
        window_start=days[0],
        window_end=days[-1],
        statuses=statuses,
        screenings=dedupe(screenings),
    )
    if out_dir is not None:
        write_snapshot(snapshot, Path(out_dir))
    return snapshot


def run_venue(
    venue,
    http,
    days: list[date],
    *,
    previous: Snapshot | None = None,
    clock: Clock = now_msk,
) -> tuple[VenueStatus, list[Screening]]:
    venue_id = venue.ID
    wanted = set(days)
    started = time.monotonic()
    requests_before = _request_count(http)
    raw: list[tuple[str, str]] = []
    items: list[Screening] = []
    error: str | None = None

    try:
        raw = list(venue.fetch(http, days))
    except Exception as exc:
        error = f"fetch failed: {type(exc).__name__}: {exc}"
        log.warning("%s: %s", venue_id, error)

    if error is None:
        try:
            parsed = list(venue.parse(raw, days))
            items = [s for s in dedupe(parsed) if s.day in wanted]
        except Exception as exc:
            error = f"parse failed: {type(exc).__name__}: {exc}"
            log.warning("%s: %s", venue_id, error)

    suspicious = False
    if error is None and not items and bool(getattr(venue, "DAILY", False)) and not _any_legit_empty(venue, raw):
        suspicious = True
        error = "no screenings parsed and no «no sessions» marker found (page structure may have changed)"
        log.warning("%s: %s", venue_id, error)

    finished = clock().astimezone(MSK)
    seconds = round(time.monotonic() - started, 3)
    requests_made = max(0, _request_count(http) - requests_before)

    if error is None:
        status = VenueStatus(
            venue=venue_id,
            ok=True,
            count=len(items),
            fetched_at=finished,
            warning=_warning(venue, raw),
            requests=requests_made,
            seconds=seconds,
        )
        return status, items

    carried_at, carried = _carry_over(previous, venue_id, wanted, finished)
    if carried:
        log.warning("%s: reusing %d screenings fetched at %s", venue_id, len(carried), carried_at)
        status = VenueStatus(
            venue=venue_id,
            ok=False,
            count=len(carried),
            fetched_at=carried_at,
            stale=True,
            suspicious=suspicious,
            error=error,
            requests=requests_made,
            seconds=seconds,
        )
        return status, carried

    status = VenueStatus(
        venue=venue_id,
        ok=False,
        count=0,
        fetched_at=None,
        suspicious=suspicious,
        error=error,
        requests=requests_made,
        seconds=seconds,
    )
    return status, []


def write_snapshot(snapshot: Snapshot, out_dir: Path) -> tuple[Path, Path]:
    docs = Path(out_dir) / config.DOCS_DIRNAME
    docs.mkdir(parents=True, exist_ok=True)
    data = snapshot.to_json()
    screenings_path = docs / config.SCREENINGS_FILENAME
    status_path = docs / config.STATUS_FILENAME
    screenings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status_path.write_text(json.dumps(data["statuses"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return screenings_path, status_path


def load_snapshot(path: Path | str) -> Snapshot | None:
    """Read a previously written screenings.json; None when absent or unreadable."""
    file = Path(path)
    if not file.is_file():
        return None
    try:
        return Snapshot.from_json(json.loads(file.read_text(encoding="utf-8")))
    except Exception as exc:
        log.warning("could not load previous snapshot %s: %s", file, exc)
        return None


def _request_count(http) -> int:
    value = getattr(http, "request_count", 0)
    return value if isinstance(value, int) else 0


def _any_legit_empty(venue, raw: list[tuple[str, str]]) -> bool:
    checker = getattr(venue, "legit_empty", None)
    if checker is None:
        return False
    for _label, body in raw:
        try:
            if checker(body):
                return True
        except Exception as exc:
            log.debug("%s: legit_empty raised %s", getattr(venue, "ID", "?"), exc)
    return False


def _warning(venue, raw: list[tuple[str, str]]) -> str | None:
    hook = getattr(venue, "warning", None)
    if hook is None:
        return None
    try:
        text = hook(raw)
    except Exception as exc:
        log.debug("%s: warning hook raised %s", getattr(venue, "ID", "?"), exc)
        return None
    return str(text) if text else None


def _carry_over(
    previous: Snapshot | None,
    venue_id: str,
    wanted: set[date],
    now: datetime,
) -> tuple[datetime | None, list[Screening]]:
    if previous is None:
        return None, []
    status = next((s for s in previous.statuses if s.venue == venue_id), None)
    if status is None or status.fetched_at is None or not (status.ok or status.stale):
        return None, []
    if now - status.fetched_at > timedelta(hours=config.STALE_MAX_AGE_HOURS):
        return None, []
    items = [s for s in previous.screenings if s.venue == venue_id and s.day in wanted]
    if not items:
        return None, []
    return status.fetched_at, items
