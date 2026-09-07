"""Adapter construction and credential setup helpers for CLI workflows."""

from __future__ import annotations

from typing import Callable

from kim_sectors.config import SectorsConfig
from kim_sectors.market_data import SectorsHttpAdapter, SectorsMarketData
from kim_sectors.outputs.telegram import TelegramHttpSender, TelegramSender


def build_market_data(
    config: SectorsConfig,
    factory: Callable[[SectorsConfig], SectorsMarketData] | None = None,
) -> SectorsMarketData:
    """Build the configured live market-data adapter, or a controlled test adapter."""
    return factory(config) if factory is not None else SectorsHttpAdapter(config)


def build_telegram_sender(
    config: SectorsConfig,
    factory: Callable[[SectorsConfig], TelegramSender] | None = None,
) -> TelegramSender | None:
    """Build the delivery sender when complete Telegram credentials are configured.

    A injected factory (the controlled test adapter) takes precedence; without
    one, delivery is enabled only when both the bot token and chat id are set.
    """
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
