"""Public market-data seam used by live and controlled adapters."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from .models import BrokerSummary, DailyBar


@runtime_checkable
class SectorsMarketData(Protocol):
    """Only the two observations needed by the Sectors tracer."""

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]: ...

    def fetch_broker_summary(
        self, symbol: str, start: date, end: date
    ) -> BrokerSummary: ...
