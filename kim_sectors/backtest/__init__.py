"""Backtest seam: point-in-time replay, next-session entry, and metrics."""

from .engine import ENTRY_TIMING, STARTING_CAPITAL, run_backtest
from .models import (
    BacktestConfig,
    BacktestReport,
    BenchmarkComparison,
    CoverageReport,
    EquityPoint,
    PeriodReturn,
    RebalanceEvent,
    SymbolCoverage,
    TradeRecord,
)

DEFAULT_TOP_K = 3
DEFAULT_REBALANCE_SESSIONS = 21
DEFAULT_COST_BPS = 10
DEFAULT_SLIPPAGE_BPS = 5

__all__ = [
    "BacktestConfig",
    "BacktestReport",
    "BenchmarkComparison",
    "CoverageReport",
    "DEFAULT_COST_BPS",
    "DEFAULT_REBALANCE_SESSIONS",
    "DEFAULT_SLIPPAGE_BPS",
    "DEFAULT_TOP_K",
    "ENTRY_TIMING",
    "EquityPoint",
    "PeriodReturn",
    "RebalanceEvent",
    "STARTING_CAPITAL",
    "SymbolCoverage",
    "TradeRecord",
    "run_backtest",
]