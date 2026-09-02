"""Representative Sectors tracer shared by both market-data adapters."""

from __future__ import annotations

import re
from datetime import date, datetime
from logging import Logger
from zoneinfo import ZoneInfo

from .base import SectorsMarketData
from .errors import SectorsSchemaError
from .models import PingReport
from ..observability import log_stage

DEFAULT_PING_SYMBOL = "BBCA"
MIN_PING_WINDOW_DAYS = 1
MAX_PING_WINDOW_DAYS = 14
PING_CREDITS = 2
_SYMBOL_PATTERN = re.compile(r"^[A-Z]{4}(?:\.JK)?$")


def _same_symbol(left: str, right: str) -> bool:
    """Compare IDX symbols with or without the API's ``.JK`` suffix."""
    return left.removesuffix(".JK") == right.removesuffix(".JK")


def ping_sectors(
    client: SectorsMarketData,
    *,
    symbol: str = DEFAULT_PING_SYMBOL,
    window_days: int = 7,
    timezone: ZoneInfo,
    logger: Logger,
    today: date | None = None,
) -> PingReport:
    """Fetch one LQ45 symbol and broker summary as a live-data tracer.

    The first successful response proves authentication; there is no separate
    auth probe because that would spend another API credit. ``window_days``
    stays below the broker-summary endpoint's limit.
    """
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("symbol must contain four uppercase letters, optionally followed by .JK")
    if not MIN_PING_WINDOW_DAYS <= window_days <= MAX_PING_WINDOW_DAYS:
        raise ValueError(
            f"window-days must be between {MIN_PING_WINDOW_DAYS} and {MAX_PING_WINDOW_DAYS}"
        )

    window_end = today or datetime.now(timezone).date()
    window_start = date.fromordinal(window_end.toordinal() - window_days + 1)
    daily = client.fetch_daily_bars(symbol, window_start, window_end)
    broker_summary = client.fetch_broker_summary(symbol, window_start, window_end)
    log_stage(logger, "auth", endpoint=f"/v2/daily/{symbol}/", status="ok")
    log_stage(
        logger,
        "fetch",
        endpoints=[f"/v2/daily/{symbol}/", f"/v2/broker-summary/{symbol}/"],
        daily_rows=len(daily),
        broker_rows=len(broker_summary.data),
        status="ok",
    )
    log_stage(
        logger,
        "validate",
        daily_rows=len(daily),
        broker_days=len(broker_summary.data),
        status="ok",
    )
    if not daily or not broker_summary.data:
        raise SectorsSchemaError("Sectors returned no daily bars or broker-summary days")

    if not _same_symbol(broker_summary.symbol, symbol) or any(
        not _same_symbol(bar.symbol, symbol) for bar in daily
    ):
        raise SectorsSchemaError("Sectors response symbol does not match requested symbol")

    if broker_summary.start != window_start or broker_summary.end != window_end:
        raise SectorsSchemaError("Sectors broker-summary range does not match requested window")

    report = PingReport(
        symbol=symbol,
        window_start=window_start,
        window_end=window_end,
        daily_bars=daily,
        broker_summary=broker_summary,
        credits_spent=PING_CREDITS,
        completed_at=datetime.now(timezone),
    )
    log_stage(
        logger,
        "complete",
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        credits_spent=report.credits_spent,
        status="ok",
    )
    return report
