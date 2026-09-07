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


def test_qualifies_buy_activity_raises_contextual_cache_error():
    from kim_sectors.market_data.errors import CacheError
    from kim_sectors.strategy.signal import _qualifies_buy_activity

    day = date(2026, 8, 10)
    with pytest.raises(CacheError) as exc_non_dict:
        _qualifies_buy_activity(["not-a-dict"], symbol="BBCA", day=day)
    assert "Cached broker row for BBCA on 2026-08-10 has malformed summary row 0: expected dict, got str" in str(exc_non_dict.value)

    with pytest.raises(CacheError) as exc_bad_num:
        _qualifies_buy_activity([{"bval": "invalid", "blot": 1, "nval": "10"}], symbol="BBCA", day=day)
    assert "Cached broker row for BBCA on 2026-08-10 has malformed summary row 0" in str(exc_bad_num.value)


def test_load_broker_dates_raises_contextual_cache_error_for_malformed_summary(monkeypatch, tmp_path):
    from kim_sectors.market_data.errors import CacheError
    from kim_sectors.strategy.signal import _load_broker_dates

    day = date(2026, 8, 10)
    monkeypatch.setattr(
        "kim_sectors.strategy.signal.read_cache",
        lambda symbol, data_type, cache_dir: ([{"date": day.isoformat(), "summary": "not-a-list"}], []),
    )
    with pytest.raises(CacheError) as exc_info:
        _load_broker_dates("BBCA", tmp_path, day)
    assert "Cached broker row for BBCA on 2026-08-10 has a malformed summary" in str(exc_info.value)


def test_load_broker_dates_rejects_net_selling(monkeypatch, tmp_path):
    from kim_sectors.strategy.signal import _load_broker_dates

    day = date(2026, 8, 10)
    # Buy value positive but net value negative (net selling)
    summary_net_selling = [{"bval": "100", "blot": 1, "nval": "-50"}]
    monkeypatch.setattr(
        "kim_sectors.strategy.signal.read_cache",
        lambda symbol, data_type, cache_dir: ([{"date": day.isoformat(), "summary": summary_net_selling}], []),
    )
    assert _load_broker_dates("BBCA", tmp_path, day) == set()

