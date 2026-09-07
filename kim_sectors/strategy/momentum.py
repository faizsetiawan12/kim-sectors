"""Trailing momentum calculation over available trading sessions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

DEFAULT_MOMENTUM_LOOKBACK = 21


def momentum_return(start_close: Decimal, end_close: Decimal) -> float:
    """Return trailing percentage return ``(end - start) / start``.

    Callers validate prices are positive; this guards the arithmetic boundary.
    """
    if start_close <= 0 or end_close <= 0:
        raise ValueError("momentum requires positive start and end closes")
    try:
        return float((end_close - start_close) / start_close)
    except (ZeroDivisionError, InvalidOperation, ArithmeticError) as error:
        raise ValueError(f"momentum calculation failed: {error}") from error
