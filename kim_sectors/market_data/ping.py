"""Representative Sectors tracer shared by both market-data adapters."""

from __future__ import annotations

import re
from datetime import date, datetime
from logging import Logger
from zoneinfo import ZoneInfo

from .base import SectorsMarketData
from .models import PingReport
from ..observability import log_stage

DEFAULT_PING_SYMBOL = "BBCA"
_SYMBOL_PATTERN = re.compile(r"^[A-Z]{4}(?:\.JK)?$")


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
    stays below the broker-summary endpoint's fourteen-day limit.
    """
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("symbol must contain four uppercase letters, optionally followed by .JK")
    if not 1 <= window_days <= 14:
        raise ValueError("window-days must be between 1 and 14")

    window_end = today or datetime.now(timezone).date()
    window_start = date.fromordinal(window_end.toordinal() - window_days + 1)
    daily = client.fetch_daily_bars(symbol, window_start, window_end)
    log_stage(logger, "auth", endpoint=f"/v2/daily/{symbol}/", status="ok")
    broker_summary = client.fetch_broker_summary(symbol, window_start, window_end)
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
    report = PingReport(
        symbol=symbol,
        window_start=window_start,
        window_end=window_end,
        daily_bars=daily,
        broker_summary=broker_summary,
        credits_spent=2,
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
