"""Sync-cache behavior over windows containing non-trading days.

Live Sectors responses omit weekends and IDX holidays. Coverage validation
must accept calendar gaps and only reject bars that are out of bounds,
duplicated, or unsorted.
"""

from __future__ import annotations

import json
from datetime import date
from io import StringIO
from pathlib import Path

from main import main
from kim_sectors.market_data import InMemorySectorsAdapter

from .support import broker_summary_payload

def trading_days(start: date, end: date) -> list[date]:
    """Calendar days from start to end excluding weekends."""
    return [
        date.fromordinal(day)
        for day in range(start.toordinal(), end.toordinal() + 1)
        if date.fromordinal(day).weekday() < 5
    ]

def market_days_adapter(symbols: list[str]) -> InMemorySectorsAdapter:
    """Adapter whose responses contain only weekday rows, like the live API."""
    return InMemorySectorsAdapter(
        universe=symbols,
        daily=lambda symbol, start, end: [
            {
                "symbol": symbol,
                "date": day.isoformat(),
                "close": 9400.0,
                "open": 9350.0,
                "high": 9450.0,
                "low": 9300.0,
                "volume": 1000000,
                "market_cap": 100000000000.0,
            }
            for day in trading_days(start, end)
        ],
        broker_summary=lambda symbol, start, end: {
            **broker_summary_payload(symbol, start=start, end=end),
            "data": [{"date": day.isoformat(), "summary": []} for day in trading_days(start, end)],
        },
    )

def run_sync(monkeypatch, tmp_path: Path, adapter, *extra: str):
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    output, error = StringIO(), StringIO()
    result = main(
        ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-03", *extra],
        build_market_data=lambda _config: adapter,
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )
    return result, output, error

def test_sync_cache_fetch_over_weekend_succeeds(monkeypatch, tmp_path):
    # Weekend rows are omitted, but the in-range Monday row is retained.
    adapter = market_days_adapter(["BBCA"])
    result, output, error = run_sync(monkeypatch, tmp_path, adapter, "--fetch")

    assert result == 0
    assert "coverage" not in error.getvalue()
    daily = json.loads((tmp_path / "cache" / "daily" / "BBCA.json").read_text())
    assert [row["date"] for row in daily["rows"]] == ["2026-08-03"]
    assert daily["covered_spans"] == [{"start": "2026-08-01", "end": "2026-08-03"}]

def test_sync_cache_fetch_normalizes_out_of_order_daily_rows(monkeypatch, tmp_path):
    adapter = market_days_adapter(["BBCA"])
    raw_daily = adapter._daily

    def reversed_daily(symbol, start, end):
        return list(reversed(raw_daily(symbol, start, end)))

    adapter._daily = reversed_daily
    result, output, error = run_sync(monkeypatch, tmp_path, adapter, "--fetch")

    assert result == 0
    assert error.getvalue() == ""
    daily = json.loads((tmp_path / "cache" / "daily" / "BBCA.json").read_text())
    assert [row["date"] for row in daily["rows"]] == ["2026-08-03"]


def test_sync_cache_does_not_overstate_partial_daily_coverage(monkeypatch, tmp_path):
    # Requested window is Mon 2026-08-03 to Fri 2026-08-07 (5 trading days).
    # Response returns only Mon 3rd and Tue 4th. Wed, Thu, Fri are unreturned trading days.
    adapter = InMemorySectorsAdapter(
        universe=["BBCA"],
        daily=lambda symbol, start, end: [
            {
                "symbol": symbol,
                "date": "2026-08-03",
                "close": 9400.0,
                "open": 9350.0,
                "high": 9450.0,
                "low": 9300.0,
                "volume": 1000000,
                "market_cap": 100000000000.0,
            },
            {
                "symbol": symbol,
                "date": "2026-08-04",
                "close": 9450.0,
                "open": 9400.0,
                "high": 9500.0,
                "low": 9350.0,
                "volume": 1000000,
                "market_cap": 100000000000.0,
            },
        ],
        broker_summary=lambda symbol, start, end: {
            **broker_summary_payload(symbol, start=start, end=end),
            "data": [
                {"date": "2026-08-03", "summary": []},
                {"date": "2026-08-04", "summary": []},
            ],
        },
    )
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    output, error = StringIO(), StringIO()
    result = main(
        ["sync-cache", "--start", "2026-08-03", "--end", "2026-08-07", "--fetch"],
        build_market_data=lambda _config: adapter,
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )

    assert result == 0
    assert error.getvalue() == ""
    daily = json.loads((tmp_path / "cache" / "daily" / "BBCA.json").read_text())
    assert [row["date"] for row in daily["rows"]] == ["2026-08-03", "2026-08-04"]
    # Coverage must not overstate to 2026-08-07 when Wed-Fri were not returned
    assert daily["covered_spans"] == [{"start": "2026-08-03", "end": "2026-08-04"}]


def test_sync_cache_fetch_normalizes_out_of_order_broker_days(monkeypatch, tmp_path):
    adapter = market_days_adapter(["BBCA"])
    raw_broker = adapter._broker_summary

    def reversed_broker(symbol, start, end):
        payload = raw_broker(symbol, start, end)
        return {**payload, "data": list(reversed(payload["data"]))}

    adapter._broker_summary = reversed_broker
    result, output, error = run_sync(monkeypatch, tmp_path, adapter, "--fetch")

    assert result == 0
    assert error.getvalue() == ""
    broker = json.loads((tmp_path / "cache" / "broker" / "BBCA.json").read_text())
    assert [row["date"] for row in broker["rows"]] == ["2026-08-03"]


def test_sync_cache_repeat_fetches_remainder_after_partial_coverage(monkeypatch, tmp_path):
    # First sync returns Mon 3rd - Tue 4th for a Mon 3rd - Fri 7th window.
    # Second sync fetches the remaining Wed 5th - Fri 7th chunk and merges spans.
    calls: list[tuple[str, str, date, date]] = []

    def daily_handler(symbol, start, end):
        calls.append(("daily", symbol, start, end))
        if start == date(2026, 8, 3):
            return [
                {
                    "symbol": symbol,
                    "date": "2026-08-03",
                    "close": 9400.0,
                    "open": 9350.0,
                    "high": 9450.0,
                    "low": 9300.0,
                    "volume": 1000000,
                    "market_cap": 100000000000.0,
                },
                {
                    "symbol": symbol,
                    "date": "2026-08-04",
                    "close": 9450.0,
                    "open": 9400.0,
                    "high": 9500.0,
                    "low": 9350.0,
                    "volume": 1000000,
                    "market_cap": 100000000000.0,
                },
            ]
        return [
            {
                "symbol": symbol,
                "date": day.isoformat(),
                "close": 9500.0,
                "open": 9450.0,
                "high": 9550.0,
                "low": 9400.0,
                "volume": 1000000,
                "market_cap": 100000000000.0,
            }
            for day in trading_days(start, end)
        ]

    adapter = InMemorySectorsAdapter(
        universe=["BBCA"],
        daily=daily_handler,
        broker_summary=lambda symbol, start, end: {
            **broker_summary_payload(symbol, start=start, end=end),
            "data": [
                {"date": day.isoformat(), "summary": []}
                for day in (
                    [date(2026, 8, 3), date(2026, 8, 4)]
                    if start == date(2026, 8, 3)
                    else trading_days(start, end)
                )
            ],
        },
    )
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))

    # Pass 1: partial return
    assert (
        main(
            ["sync-cache", "--start", "2026-08-03", "--end", "2026-08-07", "--fetch"],
            build_market_data=lambda _config: adapter,
            stdout=StringIO(),
            stderr=StringIO(),
            today=lambda: date(2026, 9, 2),
        )
        == 0
    )
    daily = json.loads((tmp_path / "cache" / "daily" / "BBCA.json").read_text())
    assert daily["covered_spans"] == [{"start": "2026-08-03", "end": "2026-08-04"}]

    # Pass 2: repeat sync requests missing remainder (2026-08-05 to 2026-08-07)
    calls.clear()
    assert (
        main(
            ["sync-cache", "--start", "2026-08-03", "--end", "2026-08-07", "--fetch"],
            build_market_data=lambda _config: adapter,
            stdout=StringIO(),
            stderr=StringIO(),
            today=lambda: date(2026, 9, 2),
        )
        == 0
    )
    assert calls == [("daily", "BBCA", date(2026, 8, 5), date(2026, 8, 7))]
    daily_updated = json.loads((tmp_path / "cache" / "daily" / "BBCA.json").read_text())
    assert [row["date"] for row in daily_updated["rows"]] == [
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
    ]
    assert daily_updated["covered_spans"] == [{"start": "2026-08-03", "end": "2026-08-07"}]


def test_sync_cache_fetch_rejects_out_of_bounds_daily_rows(monkeypatch, tmp_path):
    adapter = market_days_adapter(["BBCA"])
    raw_daily = adapter._daily
    def leaking_daily(symbol, start, end):
        rows = raw_daily(symbol, start, end)
        return rows + [dict(rows[-1], date=end.isoformat()[:8] + "04")]
    adapter._daily = leaking_daily
    result, output, error = run_sync(monkeypatch, tmp_path, adapter, "--fetch")

    assert result == 3
    assert "range" in error.getvalue()

def test_sync_cache_fetch_skips_indonesian_exchange_holidays(monkeypatch, tmp_path):
    # Independence Day (2026-08-17) is a weekday holiday on IDX.
    # Response spans 2026-08-14 (Fri) to 2026-08-18 (Tue), omitting weekend and Mon 17th.
    holiday = date(2026, 8, 17)
    adapter = InMemorySectorsAdapter(
        universe=["BBCA"],
        daily=lambda symbol, start, end: [
            {
                "symbol": symbol,
                "date": day.isoformat(),
                "close": 9400.0,
                "open": 9350.0,
                "high": 9450.0,
                "low": 9300.0,
                "volume": 1000000,
                "market_cap": 100000000000.0,
            }
            for day in trading_days(start, end)
            if day != holiday
        ],
        broker_summary=lambda symbol, start, end: {
            **broker_summary_payload(symbol, start=start, end=end),
            "data": [
                {"date": day.isoformat(), "summary": []}
                for day in trading_days(start, end)
                if day != holiday
            ],
        },
    )
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    output, error = StringIO(), StringIO()
    result = main(
        ["sync-cache", "--start", "2026-08-14", "--end", "2026-08-18", "--fetch"],
        build_market_data=lambda _config: adapter,
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )

    assert result == 0
    assert error.getvalue() == ""
    daily = json.loads((tmp_path / "cache" / "daily" / "BBCA.json").read_text())
    assert [row["date"] for row in daily["rows"]] == ["2026-08-14", "2026-08-18"]
    assert daily["covered_spans"] == [{"start": "2026-08-14", "end": "2026-08-18"}]
