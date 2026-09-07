"""Tests for strategy factor calculation edge cases, zero-division, and broker qualification."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import pytest

from kim_sectors.strategy.broker_ev import broker_ev_stats, next_session_returns
from kim_sectors.strategy.momentum import momentum_return


def test_momentum_return_catches_zero_division_without_name_error(monkeypatch):
    # Verify momentum_return catches ZeroDivisionError and does not throw NameError
    with pytest.raises(ValueError, match="momentum requires positive"):
        momentum_return(Decimal("0"), Decimal("100"))


def test_broker_ev_stats_no_name_error_on_zero_division():
    # Verify broker_ev_stats does not crash with NameError if zero division is caught
    with pytest.raises(ValueError, match="no losses"):
        broker_ev_stats([0.1, 0.2])


def test_momentum_return_zero_division_yields_value_error_not_name_error():
    class ZeroDivDec(Decimal):
        def __rtruediv__(self, other):
            raise ZeroDivisionError("zero division")

    with pytest.raises(ValueError, match="momentum calculation failed"):
        momentum_return(ZeroDivDec("10"), ZeroDivDec("20"))

    try:
        momentum_return(ZeroDivDec("10"), ZeroDivDec("20"))
    except ValueError:
        pass
    except NameError as e:  # pragma: no cover - regression guard
        pytest.fail(f"momentum_return leaked {type(e).__name__}: {e}")


def test_broker_ev_return_zero_division_yields_value_error_not_name_error():
    class ZeroDivDec(Decimal):
        def __rtruediv__(self, other):
            raise ZeroDivisionError("zero division")

    closes = [(date(2026, 8, 10), ZeroDivDec("10"), "10"), (date(2026, 8, 11), ZeroDivDec("20"), "20")]
    try:
        next_session_returns(closes, {date(2026, 8, 10)}, date(2026, 8, 11))
    except ValueError as error:
        assert "broker EV calculation failed" in str(error)
    except NameError as e:  # pragma: no cover - regression guard
        pytest.fail(f"next_session_returns leaked {type(e).__name__}: {e}")


def test_broker_ev_stats_zero_division_yields_value_error_not_name_error(monkeypatch):
    from decimal import InvalidOperation

    # Force avg_gain division inside Decimal path to raise zero division
    class ZeroDivDecimal(Decimal):
        def __truediv__(self, other):
            if other == Decimal(0):
                raise ZeroDivisionError("zero division")
            if isinstance(other, ZeroDivDecimal):
                raise InvalidOperation("invalid")
            return Decimal.__truediv__(self, other)

    monkeypatch.setattr("kim_sectors.strategy.broker_ev.Decimal", ZeroDivDecimal)

    with pytest.raises(ValueError, match="broker EV calculation failed"):
        broker_ev_stats([0.1, -0.1])
