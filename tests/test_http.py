"""Tests for the TLS posture of the shared Http layer and the binary fetch channel."""
import pytest
import requests

from cinedigest.http import Http, HttpError, _WeakDHAdapter


def test_weak_dh_adapter_mounted_only_for_domkino():
    client = Http(sink=None)
    session = client._session
    assert isinstance(session.get_adapter("https://www.domkino.spb.ru/schedule/2026/11/06/"), _WeakDHAdapter)
    assert isinstance(session.get_adapter("https://domkino.spb.ru/x"), _WeakDHAdapter)
    assert not isinstance(session.get_adapter("https://rodinakino.ru/?date=2026/11/07"), _WeakDHAdapter)
    assert not isinstance(session.get_adapter("https://kinokassa.kinoplan24.ru/x"), _WeakDHAdapter)


def test_injected_session_is_left_alone():
    """Tests inject their own sessions; the engine must not reshape them."""
    own = requests.Session()
    client = Http(session=own, sink=None)
    assert not isinstance(own.get_adapter("https://www.domkino.spb.ru/"), _WeakDHAdapter)
    assert client._session is own


class SequenceResponse:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": "text/plain; charset=utf-8"}


class SequenceSession:
    """Answers a queued sequence of responses; the last one repeats for further retries."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        return self.responses[min(self.calls - 1, len(self.responses) - 1)]


def test_get_bytes_returns_content_unchanged_and_skips_the_archive():
    archived: list[tuple] = []
    session = SequenceSession([SequenceResponse(200, b"\x89PNG\r\n\x1a\n-binary")])
    client = Http(session=session, sink=lambda *args: archived.append(args),
                  sleep=lambda seconds: None, clock=lambda: 0.0, pause_seconds=0.0, retries=0)
    assert client.get_bytes("https://image.tmdb.org/t/p/w185/x.jpg") == b"\x89PNG\r\n\x1a\n-binary"
    assert archived == []  # байтовое тело не проходит через текстовый архив-приёмник


def test_get_bytes_shares_the_retry_machinery_with_get():
    session = SequenceSession([SequenceResponse(500, b"upstream"), SequenceResponse(200, b"fine")])
    client = Http(session=session, sink=None, sleep=lambda seconds: None, clock=lambda: 0.0,
                  pause_seconds=0.0, retries=3, backoff_seconds=(0.0,))
    assert client.get_bytes("https://image.tmdb.org/t/p/w185/x.jpg") == b"fine"
    assert session.calls == 2  # один ретрай на HTTP 500, как и у get()


def test_get_bytes_treats_4xx_as_a_failure_without_retries():
    client = Http(session=SequenceSession([SequenceResponse(404, b"no such poster")]), sink=None,
                  sleep=lambda seconds: None, clock=lambda: 0.0, pause_seconds=0.0, retries=3)
    with pytest.raises(HttpError) as exc_info:
        client.get_bytes("https://image.tmdb.org/t/p/w185/missing.jpg")
    assert exc_info.value.status == 404
