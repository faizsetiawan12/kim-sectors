"""Unit tests for the Telegram HTTP sender adapter (issue #6)."""

from __future__ import annotations

import pytest

import kim_sectors.outputs.telegram as telegram_module
from kim_sectors.outputs.telegram import TelegramDeliveryError, TelegramHttpSender


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_telegram_http_sender_posts_send_message(monkeypatch):
    sent = {}

    def fake_post(url, data, timeout):
        sent["url"] = url
        sent["data"] = data
        sent["timeout"] = timeout
        return FakeResponse(payload={"ok": True, "result": {}})

    monkeypatch.setattr(telegram_module.requests, "post", fake_post)
    sender = TelegramHttpSender(
        bot_token="TOKEN-123",
        chat_id="-100123",
        message_thread_id=7,
        timeout=5.0,
    )

    sender.send("KIM Daily Brief")

    assert sent["url"] == "https://api.telegram.org/botTOKEN-123/sendMessage"
    assert sent["data"]["chat_id"] == "-100123"
    assert sent["data"]["text"] == "KIM Daily Brief"
    assert sent["data"]["message_thread_id"] == 7
    assert sent["timeout"] == 5.0


def test_telegram_http_sender_omits_thread_id_when_unset(monkeypatch):
    sent = {}

    def fake_post(url, data, timeout):
        sent["data"] = data
        return FakeResponse(payload={"ok": True})

    monkeypatch.setattr(telegram_module.requests, "post", fake_post)
    TelegramHttpSender(bot_token="T", chat_id="C").send("hello")
    assert "message_thread_id" not in sent["data"]


def test_telegram_http_sender_raises_on_http_error(monkeypatch):
    def fake_post(url, data, timeout):
        return FakeResponse(status_code=429, payload={"ok": False})

    monkeypatch.setattr(telegram_module.requests, "post", fake_post)
    sender = TelegramHttpSender(bot_token="T", chat_id="C")
    with pytest.raises(TelegramDeliveryError, match="HTTP 429"):
        sender.send("hello")


def test_telegram_http_sender_raises_on_telegram_ok_false(monkeypatch):
    def fake_post(url, data, timeout):
        return FakeResponse(payload={"ok": False, "description": "chat not found"})

    monkeypatch.setattr(telegram_module.requests, "post", fake_post)
    sender = TelegramHttpSender(bot_token="T", chat_id="C")
    with pytest.raises(TelegramDeliveryError, match="chat not found"):
        sender.send("hello")


def test_telegram_http_sender_raises_on_network_error(monkeypatch):
    def fake_post(url, data, timeout):
        raise telegram_module.requests.ConnectionError("boom")

    monkeypatch.setattr(telegram_module.requests, "post", fake_post)
    sender = TelegramHttpSender(bot_token="T", chat_id="C")
    with pytest.raises(TelegramDeliveryError, match="request failed"):
        sender.send("hello")