"""Public market-data seams used by live and controlled adapters."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from .models import BrokerSummary, DailyBar, UniverseResolution


@runtime_checkable
class SectorsMarketData(Protocol):
    """Historical observations used by the tracer and sync workflow."""

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]: ...

    def fetch_broker_summary(
        self, symbol: str, start: date, end: date
    ) -> BrokerSummary: ...


class UniverseMarketData(Protocol):
    """Universe resolution capability kept separate from historical data."""

    def fetch_universe(self, index: str) -> UniverseResolution: ...


class SyncMarketData(SectorsMarketData, UniverseMarketData, Protocol):
    """Complete market-data capability required by cache synchronization."""
