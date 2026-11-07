"""Доставка: файлы записываются, Telegram отправляется по частям, конфигурация уважается."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from cinedigest import config, deliver
from cinedigest.model import MSK, Screening, Snapshot, VenueStatus

GEN_AT = datetime(2026, 11, 5, 9, 1, tzinfo=MSK)


def _snapshot(screenings: list[Screening]) -> Snapshot:
    statuses = [VenueStatus(venue=v, ok=True, count=0, fetched_at=None) for v in
                ("domkino", "rodina", "avrora", "poravkino", "lenfilm", "outcinema")]
    return Snapshot(
        generated_at=GEN_AT,
        window_start=datetime(2026, 11, 5).date(),
        window_end=datetime(2026, 11, 6).date(),
        statuses=statuses,
        screenings=screenings,
    )


def _screening(title: str, hour: int = 19) -> Screening:
    return Screening(
        venue="domkino",
        source_id=f"domkino|{title}|{hour}",
        title=title,
        start=datetime(2026, 11, 5, hour, 0, tzinfo=MSK),
    )


def test_write_produces_four_readable_files(tmp_path):
    snapshot = _snapshot([_screening("Сабрина")])
    html_path, digest_path = deliver.write(snapshot, tmp_path)

    assert html_path == tmp_path / "docs" / "index.html"
    assert digest_path == tmp_path / "docs" / "digest.txt"
    html = html_path.read_text(encoding="utf-8")
    digest = digest_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in html  # в принятом шаблоне перед доктайпом остаются переносы строк
    assert "Кино вечером" in html
    assert "Сабрина" in html
    assert digest.startswith("КИНО ВЕЧЕРОМ · СПб · собрано")
    assert "ИСТОЧНИКИ" in digest


class RecordResponse:
    """requests.post stub answer: HTTP-код и тело Telegram."""

    def __init__(self, *, ok: bool = True, status_code: int = 200):
        self._ok = ok
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}

    @property
    def content(self) -> bytes:
        return json.dumps({"ok": self._ok}).encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return {"ok": self._ok}


class TelegramStub:
    def __init__(self, status_code: int = 200, ok: bool = True):
        self.calls: list[tuple[str, dict]] = []
        self._response = RecordResponse(ok=ok, status_code=status_code)

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, dict(data)))
        return self._response


@pytest.fixture(autouse=True)
def clean_telegram_env(monkeypatch):
    monkeypatch.delenv(config.TELEGRAM_BOT_TOKEN_ENV, raising=False)
    monkeypatch.delenv(config.TELEGRAM_CHAT_ID_ENV, raising=False)


def test_send_telegram_posts_the_whole_text_in_order(monkeypatch):
    stub = TelegramStub()
    monkeypatch.setattr(deliver.requests, "post", stub.post)
    monkeypatch.setenv(config.TELEGRAM_BOT_TOKEN_ENV, "tok123")
    monkeypatch.setenv(config.TELEGRAM_CHAT_ID_ENV, "42")

    text = "СЕГОДНЯ\n19:00 · Дом кино · Сабрина"
    sent, reason = deliver.send_telegram(text)

    assert sent is True and reason is None
    (url, data), = stub.calls
    assert url == "https://api.telegram.org/bottok123/sendMessage"
    assert data["text"] == text
    assert data["chat_id"] == "42"
    assert data["disable_web_page_preview"] == "true"
    assert "parse_mode" not in data


def test_send_telegram_posts_every_part_in_order(monkeypatch):
    stub = TelegramStub()
    monkeypatch.setattr(deliver.requests, "post", stub.post)
    monkeypatch.setenv(config.TELEGRAM_BOT_TOKEN_ENV, "tok")
    monkeypatch.setenv(config.TELEGRAM_CHAT_ID_ENV, "1")

    long_text = "а" * 5000 + "\n\n" + "б" * 300
    sent, reason = deliver.send_telegram(long_text)

    assert sent is True
    from cinedigest.render_text import split_telegram

    expected = split_telegram(long_text)
    bodies = [data["text"] for _url, data in stub.calls]
    assert bodies == expected
    assert len(stub.calls) == len(expected) >= 2


def test_send_telegram_skips_without_env_pair(monkeypatch):
    stub = TelegramStub()
    monkeypatch.setattr(deliver.requests, "post", stub.post)

    sent, reason = deliver.send_telegram("текст")

    assert sent is False
    assert "TELEGRAM_BOT_TOKEN" in reason and "TELEGRAM_CHAT_ID" in reason
    assert stub.calls == []  # ничего не отправлено


def test_send_telegram_skips_when_env_pair_is_empty(monkeypatch):
    """GitHub Actions maps unset secrets to empty strings: an empty pair is 'not
    configured', not a crash (observed in Actions run 42358859277)."""
    stub = TelegramStub()
    monkeypatch.setattr(deliver.requests, "post", stub.post)
    monkeypatch.setenv(config.TELEGRAM_BOT_TOKEN_ENV, "")
    monkeypatch.setenv(config.TELEGRAM_CHAT_ID_ENV, "")

    sent, reason = deliver.send_telegram("текст")

    assert sent is False
    assert "TELEGRAM_BOT_TOKEN" in reason and "TELEGRAM_CHAT_ID" in reason
    assert stub.calls == []  # ничего не отправлено


def test_send_telegram_raises_on_http_error(monkeypatch):
    stub = TelegramStub(status_code=500)
    monkeypatch.setattr(deliver.requests, "post", stub.post)
    monkeypatch.setenv(config.TELEGRAM_BOT_TOKEN_ENV, "tok")
    monkeypatch.setenv(config.TELEGRAM_CHAT_ID_ENV, "1")

    with pytest.raises(Exception) as error:
        deliver.send_telegram("текст")
    assert not isinstance(error.value, RuntimeError)


def test_send_telegram_raises_on_ok_false_body(monkeypatch):
    stub = TelegramStub(ok=False)
    monkeypatch.setattr(deliver.requests, "post", stub.post)
    monkeypatch.setenv(config.TELEGRAM_BOT_TOKEN_ENV, "tok")
    monkeypatch.setenv(config.TELEGRAM_CHAT_ID_ENV, "1")

    with pytest.raises(RuntimeError):
        deliver.send_telegram("текст")


def test_telegram_text_is_built_from_snapshot(monkeypatch):
    monkeypatch.delenv(config.PAGE_URL_ENV, raising=False)
    text = deliver.telegram_text(_snapshot([_screening("Сабрина")]))
    assert text.startswith("СЕГОДНЯ ВЕЧЕРОМ")
    assert "Сабрина" in text
    monkeypatch.setenv(config.PAGE_URL_ENV, "https://pages.test/")
    assert deliver.telegram_text(_snapshot([])).endswith("https://pages.test/")
