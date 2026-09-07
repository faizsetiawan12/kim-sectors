"""Telegram notification seam: sender protocol, HTTP adapter, delivery error."""

from __future__ import annotations

from typing import Protocol

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramDeliveryError(Exception):
    """Raised when a Telegram message cannot be delivered."""


class TelegramSender(Protocol):
    """Send one text message to a configured Telegram destination."""

    def send(self, text: str) -> None: ...


class TelegramHttpSender:
    """Deliver one text message through the Telegram Bot API sendMessage."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        message_thread_id: int | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._message_thread_id = message_thread_id
        self._timeout = timeout

    def send(self, text: str) -> None:
        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        params: dict[str, object] = {"chat_id": self._chat_id, "text": text}
        if self._message_thread_id is not None:
            params["message_thread_id"] = self._message_thread_id
        try:
            response = requests.post(url, data=params, timeout=self._timeout)
        except requests.RequestException as error:
            raise TelegramDeliveryError(f"Telegram request failed: {error}") from error
        if response.status_code != 200:
            raise TelegramDeliveryError(
                f"Telegram request failed: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise TelegramDeliveryError("Telegram response was not valid JSON") from error
        if not payload.get("ok"):
            description = payload.get("description", "unknown error")
            raise TelegramDeliveryError(f"Telegram delivery failed: {description}")