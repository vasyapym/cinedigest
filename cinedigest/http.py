"""Polite HTTP layer over requests: shared headers, per-host pauses, timeouts, retries, raw-body archive hook."""
from __future__ import annotations

import logging
import re
import ssl
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from . import config

log = logging.getLogger(__name__)

# sink(venue, label, body) receives every successfully fetched body
Sink = Callable[[str, str, str], None]

_CHARSET_RE = re.compile(r"charset=([\w\-]+)", re.IGNORECASE)
_UNSAFE_FILENAME_RE = re.compile(r"[^\w.\-]+")

_WEAK_DH_HOSTS = ("www.domkino.spb.ru", "domkino.spb.ru")


class _WeakDHAdapter(HTTPAdapter):
    """TLS adapter for hosts whose servers still offer small DH keys (e.g. Dom Kino).

    OpenSSL 3.x rejects the handshake with DH_KEY_TOO_SMALL at the default security
    level; SECLEVEL=1 accepts it. Mounted ONLY for the domkino hosts, so every other
    venue keeps the strict default posture.
    """

    def init_poolmanager(self, *args: object, **kwargs: object) -> None:
        context = ssl.create_default_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = context
        super().init_poolmanager(*args, **kwargs)


class HttpError(Exception):
    """A GET failed for good: a 4xx answer, or retries exhausted on 5xx / transport errors."""

    def __init__(self, message: str, *, url: str, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status


class Http:
    """Sequential GET client. `session`, `sleep` and `clock` are injectable for tests."""

    def __init__(
        self,
        *,
        session=None,
        sink: Sink | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        pause_seconds: float = config.MIN_HOST_PAUSE_SECONDS,
        retries: int = config.RETRIES,
        backoff_seconds: tuple[float, ...] = config.BACKOFF_SECONDS,
        connect_timeout: float = config.CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = config.READ_TIMEOUT_SECONDS,
    ):
        self._session = session if session is not None else requests.Session()
        if session is None:  # the strict posture stays intact everywhere else
            for host in _WEAK_DH_HOSTS:
                self._session.mount(f"https://{host}/", _WeakDHAdapter())
        self.sink = sink
        self._sleep = sleep
        self._clock = clock
        self._pause_seconds = pause_seconds
        self._retries = retries
        self._backoff = tuple(backoff_seconds)
        self._timeout = (connect_timeout, read_timeout)
        self._last_request_at: dict[str, float] = {}
        self.request_count = 0

    def get(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        venue: str = "",
        label: str = "",
    ) -> str:
        """Return the decoded body of a successful answer; raise HttpError otherwise."""
        merged_headers = {"User-Agent": config.USER_AGENT, "Accept-Language": config.ACCEPT_LANGUAGE}
        if headers:
            merged_headers.update(headers)
        host = urlsplit(url).netloc
        attempts = self._retries + 1
        failure: HttpError | None = None
        for attempt in range(1, attempts + 1):
            self._wait_for_host(host)
            self.request_count += 1
            try:
                response = self._session.get(url, params=params, headers=merged_headers, timeout=self._timeout)
            except requests.RequestException as exc:
                self._last_request_at[host] = self._clock()
                failure = HttpError(f"{type(exc).__name__}: {exc}", url=url)
                log.warning("GET %s attempt %d/%d failed: %s", url, attempt, attempts, failure)
            else:
                self._last_request_at[host] = self._clock()
                status = response.status_code
                if status >= 500:
                    failure = HttpError(f"HTTP {status}", url=url, status=status)
                    log.warning("GET %s attempt %d/%d: HTTP %d", url, attempt, attempts, status)
                elif status >= 400:
                    raise HttpError(f"HTTP {status}", url=url, status=status)
                else:
                    body = _decode(response)
                    self._archive(venue, label, body)
                    return body
            if attempt < attempts and self._backoff:
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]
                if delay > 0:
                    self._sleep(delay)
        if failure is None:
            failure = HttpError("request was not attempted", url=url)
        raise failure

    def _wait_for_host(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is None:
            return
        remaining = self._pause_seconds - (self._clock() - last)
        if remaining > 0:
            self._sleep(remaining)

    def _archive(self, venue: str, label: str, body: str) -> None:
        if self.sink is None:
            return
        try:
            self.sink(venue, label, body)
        except Exception as exc:  # the archive is best-effort and must never break a fetch
            log.warning("archive sink failed for %s/%s: %s", venue, label, exc)


def _decode(response) -> str:
    headers = getattr(response, "headers", None) or {}
    content_type = headers.get("Content-Type", "") or ""
    match = _CHARSET_RE.search(content_type)
    encoding = match.group(1) if match else "utf-8"
    try:
        return response.content.decode(encoding, errors="replace")
    except LookupError:
        return response.content.decode("utf-8", errors="replace")


def safe_filename(name: str) -> str:
    cleaned = _UNSAFE_FILENAME_RE.sub("_", (name or "").strip()).lstrip(".")
    return cleaned or "body"


def file_sink(root: Path) -> Sink:
    """Archive sink writing <root>/<venue>/<label>; failures are logged, never raised."""

    def sink(venue: str, label: str, body: str) -> None:
        try:
            target = Path(root) / safe_filename(venue or "unknown") / safe_filename(label or "body")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        except Exception as exc:
            log.warning("could not archive %s/%s under %s: %s", venue, label, root, exc)

    return sink
