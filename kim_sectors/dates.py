"""Small date arithmetic utilities shared by workflow and market data."""

from __future__ import annotations

from datetime import date, timedelta


def add_days(value: date, days: int) -> date:
    """Return *value* shifted by a number of calendar days."""
    return value + timedelta(days=days)
