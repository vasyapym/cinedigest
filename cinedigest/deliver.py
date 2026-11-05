"""Delivery: write docs files for a snapshot and push the Telegram message."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

from . import config
from .model import Snapshot
from .render import render, render_context
from .render_text import render_digest, render_telegram, split_telegram

log = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

INDEX_FILENAME = "index.html"
DIGEST_FILENAME = "digest.txt"


def write(snapshot: Snapshot, out_dir: Path | str) -> tuple[Path, Path]:
    """Render index.html and digest.txt under <out_dir>/docs/; return the two paths."""
    docs = Path(out_dir) / config.DOCS_DIRNAME
    docs.mkdir(parents=True, exist_ok=True)
    html_path = docs / INDEX_FILENAME
    digest_path = docs / DIGEST_FILENAME
    html_path.write_text(render(snapshot), encoding="utf-8")
    context = render_context(snapshot)
    digest_path.write_text(
        render_digest(context["days"], context["evening"], snapshot.statuses,
                      snapshot.generated_at, context["today"]),
        encoding="utf-8",
    )
    return html_path, digest_path


def telegram_text(snapshot: Snapshot, page_url: str | None = None) -> str:
    """The full Telegram body for the snapshot. The trailing page URL comes from
    the explicit argument or, when unset, from CINEDIGEST_PAGE_URL (Q4: opt-in)."""
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
