"""Controlled in-memory market-data adapter for command-level tests."""

from __future__ import annotations

from datetime import date
from typing import Any

from .errors import MarketDataError
from .models import BrokerSummary, DailyBar
from .validate import parse_broker_summary, parse_daily_bars


class InMemorySectorsAdapter:
    """Return controlled payloads through the same validation path as HTTP."""

    def __init__(
        self,
        *,
        daily: Any,
        broker_summary: Any,
        error: MarketDataError | None = None,
    ) -> None:
        self._daily = daily
        self._broker_summary = broker_summary
        self._error = error
        self.calls: list[tuple[str, str, date, date]] = []

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        self.calls.append(("daily", symbol, start, end))
        self._raise_error()
        return parse_daily_bars(self._daily, endpoint=f"/daily/{symbol}/")

    def fetch_broker_summary(
        self, symbol: str, start: date, end: date
    ) -> BrokerSummary:
        self.calls.append(("broker-summary", symbol, start, end))
        self._raise_error()
        return parse_broker_summary(
            self._broker_summary, endpoint=f"/broker-summary/{symbol}/"
        )

    def _raise_error(self) -> None:
        if self._error is not None:
            raise self._error
