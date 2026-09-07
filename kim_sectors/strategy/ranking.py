"""Momentum ranking over validated Data Cache records."""

from __future__ import annotations

from datetime import date
from logging import Logger
from pathlib import Path

from ..market_data.errors import CacheError
from ..observability import log_stage
from .cache_access import load_closes, select_membership
from .models import IneligibleCandidate, RankedCandidate, RankReport
from .momentum import momentum_return


def rank_momentum(
    *,
    index: str,
    market_date: date,
    lookback: int,
    cache_dir: Path,
    logger: Logger,
    today: date,
) -> RankReport:
    """Rank universe candidates by trailing momentum over available sessions.

    Momentum is ``(end_close / start_close - 1)`` where ``end_close`` is the
    close on ``market_date`` and ``start_close`` is the close ``lookback``
    available trading sessions earlier. This requires ``lookback + 1`` closes
    ending on ``market_date``. Non-trading-day gaps are skipped by
    counting available sessions, not calendar days. Only the window endpoints
    feed the formula; middle sessions are not inputs.
    """
    if lookback < 1:
        raise ValueError("--lookback must be >= 1")
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
    eligible: list[RankedCandidate] = []
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
            on_or_before = load_closes(symbol, cache_dir, market_date)
        except CacheError as error:
            mark_ineligible(symbol, str(error))
            continue
        if not on_or_before or on_or_before[-1][0] != market_date:
            mark_ineligible(symbol, f"no price on market date {market_date.isoformat()}")
            continue
        if len(on_or_before) < required:
            mark_ineligible(
                symbol,
                f"insufficient history: need {required} closes on or before "
                f"{market_date.isoformat()}, found {len(on_or_before)}",
            )
            continue
        window = on_or_before[-required:]
        start_date, start_close, start_raw = window[0]
        end_date, end_close, end_raw = window[-1]
        if start_close <= 0 or end_close <= 0:
            bad_date = start_date if start_close <= 0 else end_date
            mark_ineligible(
                symbol, f"invalid price: non-positive close on {bad_date.isoformat()}"
            )
            continue
        try:
            momentum = momentum_return(start_close, end_close)
        except ValueError as error:
            mark_ineligible(symbol, f"invalid price: {error}")
            continue
        eligible.append(
            RankedCandidate(
                symbol=symbol,
                market_date=market_date,
                momentum=momentum,
                start_date=start_date,
                end_date=end_date,
                start_close=start_raw,
                end_close=end_raw,
                lookback=lookback,
            )
        )

    eligible.sort(key=lambda c: c.momentum, reverse=True)
    log_stage(
        logger,
        "rank",
        status="ok",
        market_date=market_date.isoformat(),
        lookback=lookback,
        eligible=len(eligible),
        ineligible=len(ineligible),
    )
    report = RankReport(
        mode="rank",
        index=index,
        market_date=market_date,
        lookback=lookback,
        candidates=eligible,
        ineligible=ineligible,
        status="ok",
    )
    log_stage(
        logger,
        "complete",
        mode="rank",
        index=index,
        market_date=market_date.isoformat(),
        lookback=lookback,
        eligible=len(eligible),
        ineligible=len(ineligible),
        candidates=[c.model_dump(mode="json") for c in eligible],
        ineligible_reasons=[c.model_dump(mode="json") for c in ineligible],
        status="ok",
    )
    return report
