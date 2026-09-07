"""Opt-in Telegram delivery smoke test (issue #8).

This test is never part of normal test execution. It requires explicit
configuration and sends one bounded, harmless message to the configured
Telegram destination.

To run:
    RUN_TELEGRAM_SMOKE=1 pytest -m telegram tests/test_telegram_smoke.py
"""

from __future__ import annotations

import os

import pytest

from kim_sectors.config import SectorsConfig
from kim_sectors.outputs.telegram import TelegramHttpSender


@pytest.mark.telegram
def test_telegram_delivery_smoke_is_explicitly_opt_in():
    """Send one smoke message only when explicitly enabled and configured."""
    if os.getenv("RUN_TELEGRAM_SMOKE") != "1":
        pytest.skip("Skipping Telegram smoke test: set RUN_TELEGRAM_SMOKE=1 to opt in.")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not token.strip() or not chat_id or not chat_id.strip():
        pytest.skip(
            "Skipping Telegram smoke test: TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID are required."
        )

    thread_id = os.getenv("TELEGRAM_MESSAGE_THREAD_ID")
    message_thread_id = int(thread_id) if thread_id and thread_id.strip() else None
    sender = TelegramHttpSender(
        bot_token=token.strip(),
        chat_id=chat_id.strip(),
        message_thread_id=message_thread_id,
        timeout=15.0,
    )
    sender.send("KIM Sectors Telegram smoke check")
