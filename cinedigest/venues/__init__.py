"""Venue adapters. Each module exposes `ID`, `NAME`, `DAILY` and the functions
`fetch(http, days)`, `parse(raw, days)`, `legit_empty(body)`; optionally `warning(raw)`
for a success-with-caveat note. The helpers below are shared plumbing for the current
and later-stage adapters.
"""
from __future__ import annotations

import json
from datetime import datetime, tzinfo

from ..model import MSK


def parse_iso(value, *, assume: tzinfo) -> datetime | None:
    """ISO-8601 string → aware datetime in MSK. Accepts a trailing 'Z' on Python 3.10;
    naive values are interpreted in the `assume` zone."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=assume)
    return parsed.astimezone(MSK)


def to_int(value) -> int | None:
    """Lenient integer conversion for ints, floats and numeric strings; None otherwise."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        try:
            return int(round(float(text)))
        except ValueError:
            return None
    return None


def text_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_json(body: str, label: str, venue: str):
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{venue} {label}: body is not valid JSON") from exc
