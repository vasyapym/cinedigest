"""Tests for the TLS posture of the shared Http layer."""
import requests

from cinedigest.http import Http, _WeakDHAdapter


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
