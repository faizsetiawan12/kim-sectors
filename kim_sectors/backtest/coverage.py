"""Cache coverage checks for backtest runs.

A Backtest Run never fetches from Sectors. Before any signal math it compares
the requested window against each universe symbol's cached coverage and
reports every missing span; a missing span blocks the run and points the
operator at the explicit cache-sync operation.
"""

from __future__ import annotations

from datetime import date, timedelta
from logging import Logger
from pathlib import Path

from ..market_data.cache import merge_spans, missing_spans, read_cache
from ..market_data.models import DateSpan
from ..observability import log_stage
from .models import CoverageReport, SymbolCoverage


def _observed_trading_days(
    symbols: list[str], data_type: str, cache_dir: Path
) -> set[date]:
    """Return every date any cached symbol has a row for.

    The cache is the authority on which calendar days traded. A window
    containing only IDX holidays and weekends has no rows for *any* symbol, so
    it is not a coverage gap.
    """
    observed: set[date] = set()
    for symbol in symbols:
        rows, _ = read_cache(symbol, data_type, cache_dir)
        for row in rows:
            try:
                observed.add(date.fromisoformat(str(row.get("date"))))
            except (ValueError, TypeError):
                continue
    return observed


def _trading_gaps(
    gaps: list[DateSpan], observed: set[date]
) -> list[DateSpan]:
    """Keep only gaps that contain at least one day the market actually traded.

    ``missing_spans`` compares calendar dates, so a holiday between two
    trading days looks like a hole in the cache. Restricting a gap to days
    observed for at least one symbol separates "the market was closed" from
    "this symbol's history is incomplete", which is the distinction that
    matters: the first is expected, the second must block the run.
    """
    real: list[DateSpan] = []
    for gap in gaps:
        if not observed:
            # No reference calendar available; keep the gap so a genuinely
            # empty cache is still reported rather than silently accepted.
            real.append(gap)
            continue
        cursor = gap.start
        span_start: date | None = None
        last_hit: date | None = None
        while cursor <= gap.end:
            if cursor in observed:
                if span_start is None:
                    span_start = cursor
                last_hit = cursor
            elif span_start is not None and last_hit is not None:
                real.append(DateSpan(start=span_start, end=last_hit))
                span_start = None
                last_hit = None
            cursor += timedelta(days=1)
        if span_start is not None and last_hit is not None:
            real.append(DateSpan(start=span_start, end=last_hit))
    return real


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

    Gaps are judged against dates the market actually traded, so IDX holidays
    are not mistaken for missing history.
    """
    requested = DateSpan(start=start, end=end)
    daily_observed = _observed_trading_days(symbols, "daily", cache_dir)
    broker_observed = _observed_trading_days(symbols, "broker", cache_dir)
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
        daily_missing = _trading_gaps(
            [
                missing
                for window in d_req
                for missing in missing_spans(window, daily_spans)
            ],
            daily_observed,
        )
        broker_missing = _trading_gaps(
            [
                missing
                for window in b_req
                for missing in missing_spans(window, broker_spans)
            ],
            broker_observed,
        )
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