"""Controlled in-memory market-data adapter for command-level tests."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from .errors import MarketDataError
from .models import BrokerSummary, DailyBar, UniverseResolution
from .validate import parse_broker_summary, parse_daily_bars


def _infer_credits(endpoint: str, payload: Any) -> int:
    """Count credits the live adapter would have spent."""
    if endpoint in ("universe",):
        return 1
    return 1


class InMemorySectorsAdapter:
    """Return controlled payloads through the same validation path as HTTP.

    Accepts callables for daily/broker_summary to support per-(symbol,start,end)
    payloads needed by incremental-extension tests.  When a plain payload is
    given it is returned verbatim for every call, matching the old behaviour.
    When ``callable`` the signature is ``(symbol, start, end) -> payload``.
    """

    def __init__(
        self,
        *,
        daily: Any | None = None,
        broker_summary: Any | None = None,
        universe: list[str] | None = None,
        error: MarketDataError | None = None,
    ) -> None:
        self._daily = daily
        self._broker_summary = broker_summary
        self._universe = universe
        self._error = error
        self.calls: list[tuple[str, str, date | None, date | None]] = []

    def fetch_universe(self, index: str) -> UniverseResolution:
        self.calls.append(("universe", index, None, None))
        self._raise_error()
        if self._universe is None:
            from .errors import SectorsSchemaError

            raise SectorsSchemaError("No universe payload configured")
        return UniverseResolution(
            index=index,
            symbols=self._universe,
            pages=1,
            source="memory",
        )

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        self.calls.append(("daily", symbol, start, end))
        self._raise_error()
        payload = self._resolve_payload(symbol, start, end, "daily")
        return parse_daily_bars(payload, endpoint=f"/daily/{symbol}/")

    def fetch_broker_summary(
        self, symbol: str, start: date, end: date
    ) -> BrokerSummary:
        self.calls.append(("broker-summary", symbol, start, end))
        self._raise_error()
        payload = self._resolve_payload(symbol, start, end, "broker-summary")
        return parse_broker_summary(
            payload, endpoint=f"/broker-summary/{symbol}/"
        )

    def _resolve_payload(self, symbol: str, start: date, end: date, kind: str) -> Any:
        if kind == "daily":
            base = self._daily
        else:
            base = self._broker_summary
        if callable(base):
            return base(symbol, start, end)
        return base

    def _raise_error(self) -> None:
        if self._error is not None:
            raise self._error