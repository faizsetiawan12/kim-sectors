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

from ..market_data.cache import missing_spans, read_cache
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
) -> CoverageReport:
    """Return the coverage of ``[start, end]`` for each symbol and data type.

    Both daily bars and broker summaries must cover the full window. The
    result is ``status="ok"`` only when no symbol has any missing span.
    """
    requested = DateSpan(start=start, end=end)
    symbol_reports: list[SymbolCoverage] = []
    missing_symbols = 0
    for symbol in symbols:
        _, daily_spans = read_cache(symbol, "daily", cache_dir)
        _, broker_spans = read_cache(symbol, "broker", cache_dir)
        daily_missing = missing_spans(requested, daily_spans)
        broker_missing = missing_spans(requested, broker_spans)
        symbol_reports.append(
            SymbolCoverage(
                symbol=symbol,
                daily_missing=daily_missing,
                broker_missing=broker_missing,
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