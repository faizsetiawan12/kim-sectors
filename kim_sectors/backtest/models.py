"""Backtest run models: configuration, coverage, trades, and metrics."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from ..market_data.models import DateSpan, StrictModel


class BacktestConfig(StrictModel):
    """Immutable inputs and assumptions for one Backtest Run."""

    mode: str = "backtest"
    universe: str
    start: date
    end: date
    lookback: int = Field(ge=1)
    min_samples: int = Field(ge=1)
    top_k: int = Field(ge=1)
    rebalance_sessions: int = Field(ge=1)
    cost_bps: int = Field(ge=0)
    slippage_bps: int = Field(ge=0)
    starting_capital: float = Field(gt=0)
    universe_effective_date: date
    entry_timing: str


class SymbolCoverage(StrictModel):
    symbol: str
    daily_missing: list[DateSpan] = Field(default_factory=list)
    broker_missing: list[DateSpan] = Field(default_factory=list)


class CoverageReport(StrictModel):
    window_start: date
    window_end: date
    status: str  # "ok" when the window is fully cached, else "incomplete"
    symbols: list[SymbolCoverage] = Field(default_factory=list)


class EquityPoint(StrictModel):
    date: date
    value: float


class TradeRecord(StrictModel):
    date: date
    signal_date: date
    symbol: str
    side: str  # "buy" | "sell"
    price: float = Field(gt=0)
    quantity: float
    notional: float
    cost: float = Field(ge=0)
    slippage: float = Field(ge=0)
    note: str | None = None


class RebalanceEvent(StrictModel):
    signal_date: date
    entry_date: date | None
    target: list[str] = Field(default_factory=list)
    eligible: int = Field(ge=0)
    ineligible: int = Field(ge=0)
    entry_price_assumption: str
    skipped: list[str] = Field(default_factory=list)
    note: str | None = None


class PeriodReturn(StrictModel):
    start_date: date
    end_date: date
    value: float


class BenchmarkComparison(StrictModel):
    label: str
    total_return: float
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    note: str | None = None


class BacktestReport(StrictModel):
    mode: str = "backtest"
    config: BacktestConfig
    coverage: CoverageReport
    status: str  # "ok" when the replay completed, else "incomplete"
    observations: int = Field(ge=0)
    ineligible_observations: int = Field(ge=0)
    rebalances: int = Field(ge=0)
    trades: int = Field(ge=0)
    total_return: float
    win_rate: float | None = None
    average_period_return: float | None = None
    max_drawdown: float
    benchmark: BenchmarkComparison | None = None
    period_returns: list[PeriodReturn] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    trades_detail: list[TradeRecord] = Field(default_factory=list)
    rebalance_events: list[RebalanceEvent] = Field(default_factory=list)
    generated_at: datetime