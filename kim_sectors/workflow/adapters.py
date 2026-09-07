"""CLI adapter construction and credential boundary helpers."""

from __future__ import annotations

from typing import Callable

from kim_sectors.config import SectorsConfig
from kim_sectors.market_data import SectorsHttpAdapter, SectorsMarketData
from kim_sectors.outputs.telegram import TelegramHttpSender, TelegramSender


def build_market_data(
    config: SectorsConfig,
    factory: Callable[[SectorsConfig], SectorsMarketData] | None = None,
) -> SectorsMarketData:
    """Build the configured market-data adapter, allowing controlled tests."""
    return (factory or SectorsHttpAdapter)(config)


def build_telegram_sender(
    config: SectorsConfig,
    factory: Callable[[SectorsConfig], TelegramSender] | None = None,
) -> TelegramSender | None:
    """Build Telegram delivery when complete credentials are configured."""
    if factory is not None:
        return factory(config)

    token = config.telegram_bot_token
    chat_id = config.telegram_chat_id
    if token is None or chat_id is None:
        return None

    raw_token = token.get_secret_value().strip()
    clean_chat_id = chat_id.strip()
    if not raw_token or not clean_chat_id:
        return None

    return TelegramHttpSender(
        bot_token=raw_token,
        chat_id=clean_chat_id,
        message_thread_id=config.telegram_message_thread_id,
    )
