"""Shared validated-cache access for strategy ranking workflows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..market_data.cache import load_universe_membership_records, read_cache
from ..market_data.errors import CacheError
from ..market_data.models import UniverseMembership


def select_membership(index: str, market_date: date, cache_dir: Path) -> UniverseMembership:
    """Return the universe snapshot effective on or before ``market_date``."""
    records = load_universe_membership_records(index, cache_dir)
    if not records:
        raise CacheError(
            f"Universe '{index}' has no cached membership; run sync-cache --fetch first"
        )
    applicable = [r for r in records if r.effective_date <= market_date]
    if not applicable:
        earliest = min(r.effective_date for r in records).isoformat()
        raise CacheError(
            f"No universe membership effective on or before {market_date.isoformat()} "
            f"(earliest {earliest})"
        )
    return max(applicable, key=lambda r: (r.effective_date, r.resolved_at))


def load_closes(
    symbol: str, cache_dir: Path, market_date: date
) -> list[tuple[date, Decimal, str]]:
    """Load validated daily closes on or before ``market_date``, sorted."""
    rows, _ = read_cache(symbol, "daily", cache_dir)
    closes: list[tuple[date, Decimal, str]] = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date")))
        except (ValueError, TypeError):
            raise CacheError(f"Cached daily row for {symbol} has an invalid price")
        if day > market_date:
            continue
        try:
            raw_close = str(row.get("close"))
            close = Decimal(raw_close)
        except (ValueError, InvalidOperation, TypeError, ArithmeticError):
            raise CacheError(f"Cached daily row for {symbol} has an invalid price")
        closes.append((day, close, raw_close))
    closes.sort(key=lambda item: item[0])
    return closes


def load_momentum_window(
    symbol: str, cache_dir: Path, market_date: date, required: int
) -> tuple[list[tuple[date, Decimal, str]], list[tuple[date, Decimal, str]]]:
    """Load closes and validate a momentum window ending on ``market_date``.

    Returns the validated window of ``required`` closes ending on
    ``market_date`` together with the full history on or before
    ``market_date``. Raises ``CacheError`` for cache failures and
    ``ValueError`` for window validation failures (missing market-date close,
    insufficient history, or non-positive endpoints) so callers can turn
    these into explicit ineligibility reasons.
    """
    history = load_closes(symbol, cache_dir, market_date)
    if not history or history[-1][0] != market_date:
        raise ValueError(f"no price on market date {market_date.isoformat()}")
    if len(history) < required:
        raise ValueError(
            f"insufficient history: need {required} closes on or before "
            f"{market_date.isoformat()}, found {len(history)}"
        )
    window = history[-required:]
    start_date, start_close, _ = window[0]
    end_date, end_close, _ = window[-1]
    if start_close <= 0 or end_close <= 0:
        bad_date = start_date if start_close <= 0 else end_date
        raise ValueError(f"invalid price: non-positive close on {bad_date.isoformat()}")
    return window, history
