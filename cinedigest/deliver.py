"""Delivery: write docs files for a snapshot and push the Telegram message."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

from . import config, posters
from .model import Snapshot
from .render import INDEX_FILENAME, render_context, render_pages
from .render_text import render_digest, render_telegram, split_telegram

log = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

DIGEST_FILENAME = "digest.txt"

# Day pages are YYYY-MM-DD.html flat in docs/; those outside the window are removed on write.
DAY_PAGE_GLOB = "????-??-??.html"


def write(snapshot: Snapshot, out_dir: Path | str) -> tuple[Path, Path]:
    """Render index.html, one page per window day and digest.txt under <out_dir>/docs/;
    return (index path, digest path). Posters come from the committed cache only — no network."""
    docs = Path(out_dir) / config.DOCS_DIRNAME
    docs.mkdir(parents=True, exist_ok=True)
    pages = render_pages(snapshot, posters.cached_urls(snapshot.screenings, docs))
    for name, html in pages.items():
        (docs / name).write_text(html, encoding="utf-8")
    prune_day_pages(docs, set(pages))
    context = render_context(snapshot)
    digest_path = docs / DIGEST_FILENAME
    digest_path.write_text(
        render_digest(context["days"], context["evening"], snapshot.statuses,
                      snapshot.generated_at, context["today"]),
        encoding="utf-8",
    )
    return docs / INDEX_FILENAME, digest_path


def prune_day_pages(docs: Path, keep: set[str]) -> list[Path]:
    """Delete date-named pages that are not part of this render (days that left the window)."""
    removed: list[Path] = []
    for page in sorted(Path(docs).glob(DAY_PAGE_GLOB)):
        if page.name not in keep:
            page.unlink()
            removed.append(page)
            log.info("removed %s (outside the window)", page)
    return removed


def telegram_text(snapshot: Snapshot, page_url: str | None = None) -> str:
    """The full Telegram body for the snapshot. The trailing page URL comes from
    the explicit argument or, when unset, from CINEDIGEST_PAGE_URL (opt-in)."""
    if page_url is None:
        page_url = os.environ.get(config.PAGE_URL_ENV) or None
    context = render_context(snapshot)
    return render_telegram(
        context["days"], context["evening"], snapshot.statuses,
        snapshot.generated_at, context["today"], page_url=page_url,
    )


def send_telegram(text: str) -> tuple[bool, str | None]:
    """POST every part of the message in order. Returns (False, reason) when the env
    pair is missing — a deliberate skip; raises on a bad HTTP answer or an ok:false body."""
    token = os.environ.get(config.TELEGRAM_BOT_TOKEN_ENV)
    chat_id = os.environ.get(config.TELEGRAM_CHAT_ID_ENV)
    if token is None or chat_id is None:
        return False, (
            f"telegram is not configured: both {config.TELEGRAM_BOT_TOKEN_ENV} and "
            f"{config.TELEGRAM_CHAT_ID_ENV} must be set"
        )
    url = TELEGRAM_API_URL.format(token=token)
    parts = split_telegram(text)
    for part in parts:
        response = requests.post(
            url,
            data={"chat_id": chat_id, "text": part, "disable_web_page_preview": "true"},
            timeout=(config.CONNECT_TIMEOUT_SECONDS, config.READ_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"telegram sendMessage answered ok=false: {payload}")
    log.info("telegram: sent %d part(s)", len(parts))
    return True, None
