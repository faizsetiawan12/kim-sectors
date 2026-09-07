"""Output formatting for command-level error messages."""

from __future__ import annotations

from kim_sectors.backtest.models import BacktestReport


def format_backtest_coverage_error(report: BacktestReport) -> str:
    """Format human-readable message for incomplete cache coverage in backtest."""
    missing_symbols = [
        item.symbol
        for item in report.coverage.symbols
        if item.daily_missing or item.broker_missing
    ]
    return (
        "cache coverage incomplete for the requested window; "
        "run `sync-cache --start {} --end {} --fetch` to fetch missing "
        "history for: {}".format(
            report.config.start.isoformat(),
            report.config.end.isoformat(),
            ", ".join(missing_symbols),
        )
    )
