"""Raw next-day Broker EV estimation from historical observations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite

DEFAULT_MIN_SAMPLES = 5


def broker_ev_stats(returns: list[float]) -> dict[str, float | int]:
    """Compute raw EV stats from next-session returns, no winsorization.

    Convention (KIM MVP):
    - ``p`` = wins / n where win is return > 0 (flats count in n, not in averages).
    - ``avg_gain`` = mean of wins, 0.0 when no wins.
    - ``avg_loss`` = mean of |losses|; undefined when no losses.
    - ``reward_risk`` = avg_gain / avg_loss.
    - ``raw_ev`` = p * reward_risk - (1 - p).

    Raises ValueError with an explicit reason when the factor is undefined
    (empty sample, no wins and no losses, or no losses making reward-risk
    infinite) or non-finite. Callers turn this into an ineligible reason,
    never a silent zero.
    """
    n = len(returns)
    if n == 0:
        raise ValueError("no broker observations with observable outcomes")
    for r in returns:
        if not isfinite(r):
            raise ValueError("broker EV undefined: non-finite return")
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    if not wins and not losses:
        raise ValueError("broker EV undefined: no wins and no losses")
    if not losses:
        raise ValueError("broker EV undefined: no losses (reward-risk infinite)")
    try:
        # Decimal sums keep simple cases (e.g. three +10% wins) exact.
        dec_wins = [Decimal(str(w)) for w in wins]
        dec_losses = [Decimal(str(abs(v))) for v in losses]
        avg_gain_dec = sum(dec_wins, Decimal("0")) / Decimal(len(dec_wins)) if dec_wins else Decimal("0")
        avg_loss_dec = sum(dec_losses, Decimal("0")) / Decimal(len(dec_losses))
        reward_risk_dec = avg_gain_dec / avg_loss_dec
        p_dec = Decimal(len(wins)) / Decimal(n)
        raw_ev_dec = p_dec * reward_risk_dec - (Decimal(1) - p_dec)
        avg_gain = float(avg_gain_dec)
        avg_loss = float(avg_loss_dec)
        reward_risk = float(reward_risk_dec)
        win_prob = float(p_dec)
        raw_ev = float(raw_ev_dec)
    except (InvalidOperation, DivisionByZeroError, ArithmeticError) as error:
        raise ValueError(f"broker EV calculation failed: {error}") from error
    for value in (win_prob, avg_gain, avg_loss, reward_risk, raw_ev):
        if not isfinite(value):
            raise ValueError("broker EV undefined: non-finite factor")
    return {
        "samples": n,
        "win_prob": win_prob,
        "avg_gain": avg_gain,
        "avg_loss": avg_loss,
        "reward_risk": reward_risk,
        "raw_ev": raw_ev,
    }


def next_session_returns(
    closes: list[tuple[date, Decimal, str]],
    broker_dates: set[date],
    market_date: date,
) -> list[float]:
    """Build point-in-time next-session returns for broker observation dates.

    Only outcomes observable by ``market_date`` are included: both the
    observation close and the immediate next available daily close must exist
    with next date <= market_date. Observations on ``market_date`` itself,
    observations with no daily bar, and observations whose next session is
    unavailable or falls after ``market_date`` are excluded as unobservable
    (delayed outcomes), not as invalid. Non-positive closes and non-finite
    results raise ValueError so callers mark the factor ineligible with an
    explicit reason instead of silently dropping rows.
    """
    by_date = {day: (close, raw) for day, close, raw in closes}
    ordered_days = sorted(by_date)
    index_of = {day: i for i, day in enumerate(ordered_days)}
    returns: list[float] = []
    for obs in sorted(broker_dates):
        if obs > market_date:
            continue
        pos = index_of.get(obs)
        if pos is None:
            continue
        if pos + 1 >= len(ordered_days):
            continue
        nxt = ordered_days[pos + 1]
        if nxt > market_date:
            continue
        start_close, _ = by_date[obs]
        end_close, _ = by_date[nxt]
        if start_close <= 0 or end_close <= 0:
            bad = obs if start_close <= 0 else nxt
            raise ValueError(
                f"invalid price: non-positive close on {bad.isoformat()}"
            )
        try:
            value = float((end_close - start_close) / start_close)
        except (InvalidOperation, DivisionByZeroError, ArithmeticError) as error:
            raise ValueError(f"broker EV calculation failed: {error}") from error
        if not isfinite(value):
            raise ValueError("broker EV undefined: non-finite return")
        returns.append(value)
    return returns
