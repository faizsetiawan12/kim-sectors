"""Point-in-time backtest replay of the Momentum x Broker EV strategy.

The replay reads only validated Data Cache records: it never calls the
Sectors API. At every rebalance date the composite signal is computed with
the same point-in-time rules as the ``signal`` command (broker EV outcomes
observable by that date only), the top-k candidates become the target
portfolio, and trades execute at the next eligible market session close.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from logging import Logger
from pathlib import Path
from zoneinfo import ZoneInfo

from ..market_data.cache import read_cache
from ..market_data.errors import CacheError
from ..observability import log_stage
from ..strategy.cache_access import select_membership
from ..strategy.models import SignalReport
from ..strategy.signal import rank_signal
from .coverage import check_coverage
from .models import (
    BacktestConfig,
    BacktestReport,
    BenchmarkComparison,
    EquityPoint,
    PeriodReturn,
    RebalanceEvent,
    TradeRecord,
)

STARTING_CAPITAL = 1_000_000.0
ENTRY_TIMING = (
    "end-of-day signal enters at the next eligible market session close; "
    "entry is never earlier than one full session after the signal date"
)


def _load_daily_prices(symbol: str, cache_dir: Path) -> dict[date, Decimal]:
    """Load every cached close for one symbol, keyed by trading date."""
    rows, _ = read_cache(symbol, "daily", cache_dir)
    prices: dict[date, Decimal] = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date")))
            price = Decimal(str(row.get("close")))
        except (ValueError, TypeError):
            raise CacheError(f"Cached daily row for {symbol} has an invalid price")
        prices[day] = price
    return prices


def _benchmark_comparison(
    *,
    index: str,
    symbols: list[str],
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    start: date,
    end: date,
    starting_capital: float,
) -> BenchmarkComparison | None:
    """Equal-weight buy-and-hold benchmark from cached closes.

    Only symbols with positive closes at both window endpoints are included;
    when none qualify the benchmark is omitted (``None``) rather than guessed.
    """
    eligible = [
        symbol
        for symbol in symbols
        if start in prices.get(symbol, {})
        and end in prices.get(symbol, {})
        and prices[symbol][start] > 0
        and prices[symbol][end] > 0
    ]
    if not eligible:
        return None
    returns = {
        symbol: float(prices[symbol][end]) / float(prices[symbol][start]) - 1.0
        for symbol in eligible
    }
    total_return = sum(returns.values()) / len(returns)
    curve: list[EquityPoint] = []
    for session in sessions:
        session_returns = []
        for symbol in eligible:
            available = [d for d in prices[symbol] if d <= session]
            if available:
                last = max(available)
                session_returns.append(
                    float(prices[symbol][last]) / float(prices[symbol][start]) - 1.0
                )
        if session_returns:
            curve.append(
                EquityPoint(
                    date=session,
                    value=starting_capital
                    * (1.0 + sum(session_returns) / len(session_returns)),
                )
            )
    return BenchmarkComparison(
        label=f"{index.upper()} equal-weight buy-and-hold",
        total_return=total_return,
        equity_curve=curve,
        note=(
            f"equal-weight buy-and-hold of {len(eligible)}/{len(symbols)} "
            "universe symbols with cached endpoint closes"
        ),
    )


def run_backtest(
    *,
    index: str,
    start: date,
    end: date,
    lookback: int,
    min_samples: int,
    top_k: int,
    rebalance_sessions: int,
    cost_bps: int,
    slippage_bps: int,
    cache_dir: Path,
    logger: Logger,
    today: date,
    timezone: ZoneInfo,
    output_dir: Path | None = None,
    starting_capital: float = STARTING_CAPITAL,
) -> BacktestReport:
    """Replay the strategy over cached history and return a full report.

    Raises ValueError for invalid parameters and CacheError for a missing
    universe or unusable cache. Incomplete coverage returns a report with
    ``status="incomplete"`` so the caller can report the missing history
    instead of calculating over gaps.
    """
    if start > end:
        raise ValueError("--start must be on or before --end")
    if end > today:
        raise ValueError("--end cannot be in the future")
    if lookback < 1:
        raise ValueError("--lookback must be >= 1")
    if min_samples < 1:
        raise ValueError("--min-samples must be >= 1")
    if top_k < 1:
        raise ValueError("--top-k must be >= 1")
    if rebalance_sessions < 1:
        raise ValueError("--rebalance-sessions must be >= 1")
    if cost_bps < 0:
        raise ValueError("--cost-bps must be >= 0")
    if slippage_bps < 0:
        raise ValueError("--slippage-bps must be >= 0")

    membership = select_membership(index, start, cache_dir)
    symbols = list(membership.symbols)
    log_stage(
        logger,
        "universe",
        status="reused",
        index=index,
        members=len(symbols),
        effective_date=membership.effective_date.isoformat(),
    )

    coverage = check_coverage(
        symbols=symbols, start=start, end=end, cache_dir=cache_dir, logger=logger
    )
    config = BacktestConfig(
        universe=index,
        start=start,
        end=end,
        lookback=lookback,
        min_samples=min_samples,
        top_k=top_k,
        rebalance_sessions=rebalance_sessions,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        starting_capital=starting_capital,
        universe_effective_date=membership.effective_date,
        entry_timing=ENTRY_TIMING,
    )
    if coverage.status != "ok":
        report = BacktestReport(
            config=config,
            coverage=coverage,
            status="incomplete",
            observations=0,
            ineligible_observations=0,
            rebalances=0,
            trades=0,
            total_return=0.0,
            max_drawdown=0.0,
            generated_at=datetime.now(timezone),
        )
        log_stage(
            logger,
            "complete",
            status="incomplete",
            mode="backtest",
            index=index,
            window_start=start.isoformat(),
            window_end=end.isoformat(),
        )
        return report

    prices = {symbol: _load_daily_prices(symbol, cache_dir) for symbol in symbols}
    sessions = sorted(
        {
            day
            for by_symbol in prices.values()
            for day in by_symbol
            if start <= day <= end
        }
    )
    if not sessions:
        raise CacheError(
            f"No trading sessions cached for {index} between {start} and {end}"
        )

    signal_dates = sessions[::rebalance_sessions]
    transitions: dict[date, date] = {}
    for i in range(len(signal_dates)):
        next_index = i * rebalance_sessions + 1
        if next_index < len(sessions):
            transitions[sessions[next_index]] = signal_dates[i]

    signal_cache: dict[date, SignalReport] = {}

    def signal_at(market_date: date) -> SignalReport:
        if market_date not in signal_cache:
            signal_cache[market_date] = rank_signal(
                index=index,
                market_date=market_date,
                lookback=lookback,
                min_samples=min_samples,
                cache_dir=cache_dir,
                logger=logger,
                today=today,
            )
        return signal_cache[market_date]

    def close_on(symbol: str, day: date) -> Decimal | None:
        return prices.get(symbol, {}).get(day)

    def last_close(symbol: str, day: date) -> Decimal | None:
        available = [d for d in prices.get(symbol, {}) if d <= day]
        if not available:
            return None
        return prices[symbol][max(available)]

    cost_rate = cost_bps / 10_000.0
    slippage_rate = slippage_bps / 10_000.0

    cash = float(starting_capital)
    holdings: dict[str, float] = {}
    trades: list[TradeRecord] = []
    events: list[RebalanceEvent] = []
    equity: list[EquityPoint] = []
    observations = 0
    ineligible_observations = 0

    for session in sessions:
        if session in transitions:
            signal_date = transitions[session]
            report = signal_at(signal_date)
            observations += len(report.candidates)
            ineligible_observations += len(report.ineligible)
            target = [c.symbol for c in report.candidates[:top_k]]
            skipped: list[str] = []

            for symbol in sorted(holdings):
                if symbol in target:
                    continue
                price = close_on(symbol, session)
                if price is None or price <= 0:
                    skipped.append(symbol)
                    continue
                quantity = holdings.pop(symbol)
                notional = quantity * float(price)
                cost = notional * cost_rate
                slippage = notional * slippage_rate
                cash += notional - cost - slippage
                trades.append(
                    TradeRecord(
                        date=session,
                        signal_date=signal_date,
                        symbol=symbol,
                        side="sell",
                        price=float(price),
                        quantity=quantity,
                        notional=notional,
                        cost=cost,
                        slippage=slippage,
                    )
                )

            if target:
                allocation = cash / len(target)
                for symbol in target:
                    if symbol in holdings:
                        continue
                    price = close_on(symbol, session)
                    if price is None or price <= 0:
                        skipped.append(symbol)
                        continue
                    cost = allocation * cost_rate
                    slippage = allocation * slippage_rate
                    invested = allocation - cost - slippage
                    quantity = invested / float(price)
                    if quantity <= 0:
                        continue
                    holdings[symbol] = holdings.get(symbol, 0.0) + quantity
                    cash -= allocation
                    trades.append(
                        TradeRecord(
                            date=session,
                            signal_date=signal_date,
                            symbol=symbol,
                            side="buy",
                            price=float(price),
                            quantity=quantity,
                            notional=invested,
                            cost=cost,
                            slippage=slippage,
                        )
                    )

            events.append(
                RebalanceEvent(
                    signal_date=signal_date,
                    entry_date=session,
                    target=target,
                    eligible=len(report.candidates),
                    ineligible=len(report.ineligible),
                    entry_price_assumption=ENTRY_TIMING,
                    skipped=skipped,
                )
            )
            log_stage(
                logger,
                "rebalance",
                status="ok",
                signal_date=signal_date.isoformat(),
                entry_date=session.isoformat(),
                target=target,
                eligible=len(report.candidates),
                ineligible=len(report.ineligible),
                skipped=skipped,
            )

        position_value = 0.0
        for symbol, quantity in holdings.items():
            price = last_close(symbol, session)
            if price is not None:
                position_value += quantity * float(price)
        equity.append(EquityPoint(date=session, value=cash + position_value))

    executed_signal_dates = set(transitions.values())
    for signal_date in signal_dates:
        if signal_date in executed_signal_dates:
            continue
        report = signal_at(signal_date)
        observations += len(report.candidates)
        ineligible_observations += len(report.ineligible)
        events.append(
            RebalanceEvent(
                signal_date=signal_date,
                entry_date=None,
                target=[c.symbol for c in report.candidates[:top_k]],
                eligible=len(report.candidates),
                ineligible=len(report.ineligible),
                entry_price_assumption=ENTRY_TIMING,
                note="no next market session within the window; no entry executed",
            )
        )
        log_stage(
            logger,
            "rebalance",
            status="skipped",
            signal_date=signal_date.isoformat(),
            note="no next market session within the window",
        )

    final_value = equity[-1].value
    total_return = final_value / starting_capital - 1.0

    entry_dates = sorted(
        {event.entry_date for event in events if event.entry_date is not None}
    )
    equity_by_date = {point.date: point.value for point in equity}
    period_returns: list[PeriodReturn] = []
    for first, second in zip(entry_dates, entry_dates[1:]):
        period_returns.append(
            PeriodReturn(
                start_date=first,
                end_date=second,
                value=equity_by_date[second] / equity_by_date[first] - 1.0,
            )
        )
    if entry_dates and entry_dates[-1] != sessions[-1]:
        period_returns.append(
            PeriodReturn(
                start_date=entry_dates[-1],
                end_date=sessions[-1],
                value=equity_by_date[sessions[-1]] / equity_by_date[entry_dates[-1]] - 1.0,
            )
        )

    win_rate: float | None = None
    average_period_return: float | None = None
    if period_returns:
        win_rate = sum(1 for p in period_returns if p.value > 0) / len(period_returns)
        average_period_return = sum(p.value for p in period_returns) / len(period_returns)

    peak = equity[0].value
    max_drawdown = 0.0
    for point in equity:
        peak = max(peak, point.value)
        max_drawdown = min(max_drawdown, point.value / peak - 1.0)

    benchmark = _benchmark_comparison(
        index=index,
        symbols=symbols,
        prices=prices,
        sessions=sessions,
        start=start,
        end=end,
        starting_capital=starting_capital,
    )

    report = BacktestReport(
        config=config,
        coverage=coverage,
        status="ok",
        observations=observations,
        ineligible_observations=ineligible_observations,
        rebalances=len(events),
        trades=len(trades),
        total_return=total_return,
        win_rate=win_rate,
        average_period_return=average_period_return,
        max_drawdown=max_drawdown,
        benchmark=benchmark,
        period_returns=period_returns,
        equity_curve=equity,
        trades_detail=trades,
        rebalance_events=events,
        generated_at=datetime.now(timezone),
    )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = (
            output_dir
            / f"backtest_{index}_{start.isoformat()}_{end.isoformat()}"
            f"_l{lookback}_k{top_k}_r{rebalance_sessions}.json"
        )
        path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)
        )
        log_stage(logger, "artifact", status="ok", path=str(path))
    log_stage(
        logger,
        "complete",
        status="ok",
        mode="backtest",
        index=index,
        total_return=total_return,
        win_rate=win_rate,
        average_period_return=average_period_return,
        max_drawdown=max_drawdown,
        observations=observations,
        ineligible_observations=ineligible_observations,
        rebalances=len(events),
        trades=len(trades),
        benchmark=benchmark.total_return if benchmark else None,
    )
    return report