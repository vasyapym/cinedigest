"""CLI: `run` (fetch → snapshot → posters → pages+digest+telegram), `render`, `posters`, `fetch`.

Exit codes: 0 — every venue ok; 2 — at least one VenueStatus.ok is False (incl.
stale); 1 — a crash (caught at this boundary); argparse usage errors exit 2 by
the argparse convention.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

from . import config, deliver, pipeline, posters
from .http import Http, safe_filename
from .model import VENUES, Snapshot
from .venues import avrora, domkino, lenfilm, mirage, outcinema, poravkino, rodina

log = logging.getLogger(__name__)

# The seven adapter modules, in the canonical VENUES order.
DEFAULT_VENUES = [domkino, rodina, avrora, poravkino, lenfilm, outcinema, mirage]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cinedigest", description="вечерний кинодайджест семи кинотеатров СПб",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run_command = commands.add_parser("run", help="fetch every venue, write the snapshot, page and digest")
    run_command.add_argument("--days", type=int, default=None,
                             help="window length in days (default 7; 1 when --date is given)")
    run_command.add_argument("--date", metavar="YYYY-MM-DD", default=None,
                             help="window start date (default: today, MSK)")
    run_command.add_argument("--out", default=".",
                             help="workspace root: docs/ and snapshots/ live under it (default .)")
    run_command.add_argument("--only", default=None, help="comma-separated venue keys to fetch")
    run_command.add_argument("--no-telegram", action="store_true", help="skip the Telegram push")
    run_command.add_argument("--print", dest="print_text", action="store_true",
                             help="print the Telegram body to stdout instead of sending it")

    render_command = commands.add_parser("render", help="rebuild the page and digest from a saved snapshot, no network")
    render_command.add_argument("--out", default=".", help="workspace root with docs/ (default .)")
    render_command.add_argument("--snapshot", default=None,
                                help="screenings.json path (default <out>/docs/screenings.json)")

    posters_command = commands.add_parser(
        "posters", help="resolve TMDB posters for the saved snapshot (needs TMDB_READ_TOKEN) and rebuild the pages")
    posters_command.add_argument("--out", default=".", help="workspace root with docs/ (default .)")
    posters_command.add_argument("--snapshot", default=None,
                                 help="screenings.json path (default <out>/docs/screenings.json)")

    fetch_command = commands.add_parser("fetch", help="save one venue's raw responses, never renders")
    fetch_command.add_argument("--venue", metavar="KEY", required=True, help="venue key, e.g. rodina")
    fetch_command.add_argument("--date", metavar="YYYY-MM-DD", default=None,
                               help="single day to fetch (default: the whole 7-day window)")
    fetch_command.add_argument("--save", required=True, help="destination directory")

    return parser


def main(argv=None, venues=None) -> int:
    """CLI entry point; `venues` is injectable for tests (defaults to the six adapters)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    args._parser = parser
    handlers = {"run": _run, "render": _render_command, "posters": _posters_command, "fetch": _fetch_command}
    try:
        return handlers[args.command](args, venues)
    except Exception:
        log.exception("cinedigest crashed")
        return 1


def _run(args, venues) -> int:
    selected = _select_venues(args.only, venues, args._parser)
    start, days_number = _resolve_window(args)
    out_dir = args.out

    previous = pipeline.load_snapshot(
        f"{out_dir}/{config.DOCS_DIRNAME}/{config.SCREENINGS_FILENAME}",
    )
    if previous is None:
        log.info("no previous snapshot under %s — nothing to carry over", out_dir)
    http = Http()
    snapshot = _run_window(selected, start=start, days=days_number, previous=previous,
                           out_dir=out_dir, http=http)
    _resolve_posters(snapshot, http, out_dir)

    html_path, digest_path = deliver.write(snapshot, out_dir)
    log.info("written: %s, %s", html_path, digest_path)

    text = deliver.telegram_text(snapshot)
    if args.print_text:
        print(text)
    elif not args.no_telegram:
        sent, reason = deliver.send_telegram(text)
        if reason:
            log.info("telegram skipped: %s", reason)

    degraded = [st.venue for st in snapshot.statuses if not st.ok]
    if degraded:
        log.warning("degraded venues: %s", ", ".join(degraded))
        return 2
    return 0


def _run_window(venues, *, start: date, days: int, previous, out_dir, http=None) -> Snapshot:
    """pipeline.run with an explicit window.

    Engine fact: the frozen pipeline.run() computes its window as
    [clock().today .. today+6] with fixed length WINDOW_DAYS — there is no window
    parameter. The module-level pipeline.window() function is swapped for the
    requested window for this one call and restored right after.
    """
    requested = [start + timedelta(days=offset) for offset in range(days)]
    original = pipeline.window
    pipeline.window = lambda today, days=None: list(requested)
    try:
        return pipeline.run(venues, previous=previous, out_dir=out_dir, http=http)
    finally:
        pipeline.window = original


def _resolve_posters(snapshot: Snapshot, http, out_dir) -> None:
    """Best-effort: a resolver failure is logged, the pages still render from the cache."""
    try:
        posters.resolve(snapshot.screenings, http=http, out_dir=out_dir, today=pipeline.today_msk())
    except Exception:
        log.exception("posters: resolver failed — pages render with the cached posters only")


def _posters_command(args, _) -> int:
    out_dir = args.out
    snapshot_path = args.snapshot or f"{out_dir}/{config.DOCS_DIRNAME}/{config.SCREENINGS_FILENAME}"
    snapshot = pipeline.load_snapshot(snapshot_path)
    if snapshot is None:
        args._parser.error(f"snapshot not found or unreadable: {snapshot_path}")
    posters.resolve(snapshot.screenings, http=Http(), out_dir=out_dir, today=pipeline.today_msk())
    html_path, digest_path = deliver.write(snapshot, out_dir)
    log.info("written: %s, %s", html_path, digest_path)
    return 0


def _render_command(args, _) -> int:
    out_dir = args.out
    if args.snapshot:
        snapshot_path = args.snapshot
    else:
        snapshot_path = f"{out_dir}/{config.DOCS_DIRNAME}/{config.SCREENINGS_FILENAME}"
    snapshot = pipeline.load_snapshot(snapshot_path)
    if snapshot is None:
        args._parser.error(f"snapshot not found or unreadable: {snapshot_path}")
    html_path, digest_path = deliver.write(snapshot, out_dir)
    log.info("written: %s, %s", html_path, digest_path)
    return 0


def _fetch_command(args, venues, http=None) -> int:
    """Fetch only: each (label, body) saved to <save>/<venue-id>/<label>, never rendered."""
    modules = venues if venues is not None else DEFAULT_VENUES
    target = next((module for module in modules if module.ID == args.venue), None)
    if target is None:
        args._parser.error(f"unknown venue key {args.venue!r}; available: {', '.join(VENUES)}")
    if args.date:
        day = _parse_date(args.date, args._parser)
        days = [day]
    else:
        days = [pipeline.today_msk() + timedelta(days=offset) for offset in range(config.WINDOW_DAYS)]
    if http is None:
        http = Http()
    for label, body in target.fetch(http, days):
        path = Path(args.save) / target.ID / safe_filename(label)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        log.info("saved %s", path)
    return 0


def _select_venues(only: str | None, venues, parser: argparse.ArgumentParser) -> list:
    modules = venues if venues is not None else DEFAULT_VENUES
    if not only:
        return list(modules)
    keys = {part.strip() for part in only.split(",") if part.strip()}
    available = {module.ID for module in modules}
    unknown = sorted(keys - available)
    if unknown:
        parser.error(f"unknown --only keys: {', '.join(unknown)}; available: {', '.join(sorted(available))}")
    return [module for module in modules if module.ID in keys]


def _resolve_window(args) -> tuple[date, int]:
    """(window start, window length): --date sets the start and defaults the length to 1."""
    if args.date:
        start = _parse_date(args.date, args._parser)
        days_number = args.days if args.days is not None else 1
    else:
        start = pipeline.today_msk()
        days_number = args.days if args.days is not None else config.WINDOW_DAYS
    if days_number < 1:
        args._parser.error("--days must be 1 or more")
    return start, days_number


def _parse_date(text: str, parser) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        parser.error(f"bad date {text!r}: expected YYYY-MM-DD")
