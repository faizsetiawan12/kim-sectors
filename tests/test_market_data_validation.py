from __future__ import annotations

import pytest

from kim_sectors.market_data import SectorsSchemaError
from kim_sectors.market_data.validate import parse_broker_summary, parse_daily_bars

from .support import broker_summary_payload, daily_bars_payload


@pytest.fixture
def dates():
    from datetime import date

    return date(2026, 8, 26), date(2026, 8, 26)


def test_valid_daily_bars_are_parsed(dates):
    start, end = dates
    bars = parse_daily_bars(daily_bars_payload(start=start, end=end))
    assert len(bars) == 1
    assert bars[0].close == 9400


def test_valid_broker_summary_is_parsed(dates):
    start, end = dates
    summary = parse_broker_summary(broker_summary_payload(start=start, end=end))
    assert summary.symbol == "BBCA"
    assert summary.data[0].summary[0].broker_code == "MIR"


def test_missing_daily_field_is_a_schema_error():
    with pytest.raises(SectorsSchemaError, match="close"):
        parse_daily_bars([{"symbol": "BBCA", "date": "2026-08-26", "volume": 1}])


def test_unexpected_daily_field_is_a_schema_error():
    with pytest.raises(SectorsSchemaError, match="unexpected"):
        parse_daily_bars(
            [
                {
                    "symbol": "BBCA",
                    "date": "2026-08-26",
                    "close": 1,
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "volume": 1,
                    "market_cap": 1,
                    "unexpected": "changed-api",
                }
            ]
        )


def test_malformed_broker_date_is_a_schema_error(dates):
    start, end = dates
    payload = broker_summary_payload(start=start, end=end)
    payload["data"][0]["date"] = "not-a-date"
    with pytest.raises(SectorsSchemaError, match="date"):
        parse_broker_summary(payload)


def test_non_json_broker_body_is_a_schema_error():
    with pytest.raises(SectorsSchemaError, match="broker summary"):
        parse_broker_summary("not json")
