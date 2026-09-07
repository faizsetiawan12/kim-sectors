"""Cache coverage checks for backtest runs.

A Backtest Run never fetches from Sectors. Before any signal math it compares
the requested window against each universe symbol's cached coverage and
reports every missing span; a missing span blocks the run and points the
operator at the explicit cache-sync operation.
"""

from __future__ import annotations

from datetime import date
from logging import Logger
from pathlib import Path

from ..market_data.cache import merge_spans, missing_spans, read_cache
from ..market_data.models import DateSpan
from ..observability import log_stage
from .models import CoverageReport, SymbolCoverage


def check_coverage(
    *,
    symbols: list[str],
    start: date,
    end: date,
    cache_dir: Path,
    logger: Logger,
    windows: dict[str, list[DateSpan]] | None = None,
    daily_windows: dict[str, list[DateSpan]] | None = None,
    broker_windows: dict[str, list[DateSpan]] | None = None,
) -> CoverageReport:
    """Return cache coverage for each symbol's requested active windows.

    When ``windows`` is provided, each symbol is checked only for the
    point-in-time membership tenures in which it can be used. This avoids
    requiring data before a symbol joins or after it leaves the universe while
    still reporting every missing active span. The default checks the full
    replay window for callers without membership history.
    """
    requested = DateSpan(start=start, end=end)
    symbol_reports: list[SymbolCoverage] = []
    missing_symbols = 0
    for symbol in symbols:
        _, daily_spans = read_cache(symbol, "daily", cache_dir)
        _, broker_spans = read_cache(symbol, "broker", cache_dir)
        d_req = (
            merge_spans(daily_windows.get(symbol, []))
            if daily_windows is not None
            else merge_spans(windows.get(symbol, []))
            if windows is not None
            else [requested]
        )
        b_req = (
            merge_spans(broker_windows.get(symbol, []))
            if broker_windows is not None
            else merge_spans(windows.get(symbol, []))
            if windows is not None
            else [requested]
        )
        daily_missing = [
            missing
            for window in d_req
            for missing in missing_spans(window, daily_spans)
        ]
        broker_missing = [
            missing
            for window in b_req
            for missing in missing_spans(window, broker_spans)
        ]
        symbol_reports.append(
            SymbolCoverage(
                symbol=symbol,
                daily_missing=merge_spans(daily_missing),
                broker_missing=merge_spans(broker_missing),
            )
        )
        if daily_missing or broker_missing:
            missing_symbols += 1
    status = "incomplete" if missing_symbols else "ok"
    log_stage(
        logger,
        "coverage",
        status=status,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        symbols=len(symbol_reports),
        missing_symbols=missing_symbols,
    )
    return CoverageReport(
        window_start=start,
        window_end=end,
        status=status,
        symbols=symbol_reports,
    )