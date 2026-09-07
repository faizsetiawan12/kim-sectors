"""Composite Momentum x Broker EV signal ranking over validated cache."""

from __future__ import annotations

from datetime import date
from logging import Logger
from math import isfinite
from pathlib import Path

from decimal import Decimal, InvalidOperation

from ..market_data.cache import read_cache
from ..market_data.errors import CacheError
from ..observability import log_stage
from .broker_ev import broker_ev_stats, next_session_returns
from .cache_access import load_momentum_window, select_membership
from .models import IneligibleCandidate, SignalCandidate, SignalHighlight, SignalReport
from .momentum import momentum_return

HIGHLIGHT_NOTE = "For research and decision support only; not a buy or sell recommendation."


def _qualifies_buy_activity(
    summary: list[dict], *, symbol: str, day: date
) -> bool:
    """Return whether a broker day has buying and net accumulation.

    Broker EV observations require positive buy value or buy lots *and*
    positive net value. Invalid summary numbers are cache-data errors, not
    non-qualifying observations, so callers can report them explicitly.
    """
    buy_value = Decimal("0")
    buy_lots = 0
    net_value = Decimal("0")
    for index, row in enumerate(summary):
        if not isinstance(row, dict):
            raise CacheError(
                f"Cached broker row for {symbol} on {day} has malformed summary row "
                f"{index}: expected dict, got {type(row).__name__}"
            )
        try:
            buy_value += Decimal(str(row["bval"]))
            buy_lots += int(row["blot"])
            net_value += Decimal(str(row["nval"]))
        except (KeyError, InvalidOperation, ValueError, TypeError, ArithmeticError) as error:
            raise CacheError(
                f"Cached broker row for {symbol} on {day} has malformed summary row "
                f"{index}: {error}"
            ) from error
    return (buy_value > 0 or buy_lots > 0) and net_value > 0


def _load_broker_dates(symbol: str, cache_dir: Path, market_date: date) -> set[date]:
    """Return broker observation dates with qualifying broker-buy activity."""
    rows, _ = read_cache(symbol, "broker", cache_dir)
    dates: set[date] = set()
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date")))
        except (ValueError, TypeError):
            raise CacheError(f"Cached broker row for {symbol} has an invalid date")
        if day > market_date:
            continue
        summary = row.get("summary")
        if not isinstance(summary, list):
            raise CacheError(
                f"Cached broker row for {symbol} on {day} has a malformed summary"
            )
        if _qualifies_buy_activity(summary, symbol=symbol, day=day):
            dates.add(day)
    return dates


def rank_signal(
    *,
    index: str,
    market_date: date,
    lookback: int,
    min_samples: int,
    cache_dir: Path,
    logger: Logger,
    today: date,
) -> SignalReport:
    """Rank candidates by ``Momentum x Broker EV`` with point-in-time EV.

    Momentum is the trailing return over ``lookback`` available sessions
    ending on ``market_date``. Broker EV is estimated from historical
    broker-summary observation dates whose next-session outcome is observable
    by ``market_date`` (next close <= market_date), using raw returns with no
    winsorization: ``p * reward_risk - (1 - p)``. Missing, invalid, infinite,
    and under-sampled factors are ineligible with explicit reasons.
    """
    if lookback < 1:
        raise ValueError("--lookback must be >= 1")
    if min_samples < 1:
        raise ValueError("--min-samples must be >= 1")
    if market_date > today:
        raise ValueError("--market-date cannot be in the future")

    membership = select_membership(index, market_date, cache_dir)
    log_stage(
        logger,
        "universe",
        status="reused",
        index=index,
        members=len(membership.symbols),
        effective_date=membership.effective_date.isoformat(),
    )

    required = lookback + 1
    eligible: list[SignalCandidate] = []
    ineligible: list[IneligibleCandidate] = []

    def mark_ineligible(symbol: str, reason: str) -> None:
        ineligible.append(
            IneligibleCandidate(
                symbol=symbol,
                market_date=market_date,
                reason=reason,
                lookback=lookback,
            )
        )

    for symbol in membership.symbols:
        try:
            window, on_or_before = load_momentum_window(
                symbol, cache_dir, market_date, required
            )
        except (CacheError, ValueError) as error:
            mark_ineligible(symbol, str(error))
            continue
        start_date, start_close, start_raw = window[0]
        end_date, end_close, end_raw = window[-1]
        try:
            momentum = momentum_return(start_close, end_close)
        except ValueError as error:
            mark_ineligible(symbol, f"invalid price: {error}")
            continue
        if not isfinite(momentum):
            mark_ineligible(symbol, "invalid price: non-finite momentum")
            continue
        try:
            broker_dates = _load_broker_dates(symbol, cache_dir, market_date)
        except CacheError as error:
            mark_ineligible(symbol, str(error))
            continue
        if not broker_dates:
            mark_ineligible(symbol, "no broker observations on or before market date")
            continue
        try:
            returns = next_session_returns(on_or_before, broker_dates, market_date)
        except ValueError as error:
            mark_ineligible(symbol, str(error))
            continue
        if len(returns) < min_samples:
            mark_ineligible(
                symbol,
                f"insufficient broker samples: need {min_samples}, found {len(returns)}",
            )
            continue
        try:
            stats = broker_ev_stats(returns)
        except ValueError as error:
            mark_ineligible(symbol, str(error))
            continue
        broker_ev = stats["raw_ev"]
        reward_risk = stats["reward_risk"]
        samples = stats["samples"]
        win_prob = stats["win_prob"]
        avg_gain = stats["avg_gain"]
        avg_loss = stats["avg_loss"]
        assert isinstance(broker_ev, float)
        assert isinstance(reward_risk, float)
        assert isinstance(samples, int)
        assert isinstance(win_prob, float)
        assert isinstance(avg_gain, float)
        assert isinstance(avg_loss, float)
        signal_score = momentum * broker_ev
        if not all(isfinite(v) for v in (broker_ev, signal_score, reward_risk)):
            mark_ineligible(symbol, "ineligible: non-finite signal factor")
            continue
        eligible.append(
            SignalCandidate(
                symbol=symbol,
                market_date=market_date,
                momentum=momentum,
                samples=samples,
                win_prob=win_prob,
                avg_gain=avg_gain,
                avg_loss=avg_loss,
                reward_risk=reward_risk,
                broker_ev=broker_ev,
                signal_score=signal_score,
                start_date=start_date,
                end_date=end_date,
                start_close=start_raw,
                end_close=end_raw,
                lookback=lookback,
            )
        )

    eligible.sort(key=lambda c: (-c.signal_score, c.symbol))
    log_stage(
        logger,
        "scoring",
        status="ok",
        market_date=market_date.isoformat(),
        lookback=lookback,
        min_samples=min_samples,
        eligible=len(eligible),
        ineligible=len(ineligible),
    )
    log_stage(
        logger,
        "signal",
        status="ok",
        market_date=market_date.isoformat(),
        lookback=lookback,
        min_samples=min_samples,
        eligible=len(eligible),
        ineligible=len(ineligible),
    )
    highlight: SignalHighlight | None = None
    if eligible:
        top = eligible[0]
        highlight = SignalHighlight(
            symbol=top.symbol,
            signal_score=top.signal_score,
            momentum=top.momentum,
            broker_ev=top.broker_ev,
            note=HIGHLIGHT_NOTE,
        )
    report = SignalReport(
        mode="signal",
        index=index,
        market_date=market_date,
        lookback=lookback,
        min_samples=min_samples,
        candidates=eligible,
        ineligible=ineligible,
        highlight=highlight,
        status="ok",
    )
    log_stage(
        logger,
        "complete",
        mode="signal",
        index=index,
        market_date=market_date.isoformat(),
        lookback=lookback,
        min_samples=min_samples,
        eligible=len(eligible),
        ineligible=len(ineligible),
        candidates=[c.model_dump(mode="json") for c in eligible],
        ineligible_reasons=[c.model_dump(mode="json") for c in ineligible],
        highlight=highlight.model_dump(mode="json") if highlight else None,
        status="ok",
    )
    return report
