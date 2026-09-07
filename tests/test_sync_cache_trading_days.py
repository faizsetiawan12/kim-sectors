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

def test_sync_cache_fetch_rejects_unsorted_daily_rows(monkeypatch, tmp_path):
    adapter = market_days_adapter(["BBCA"])
    raw_daily = adapter._daily
    def reversed_daily(symbol, start, end):
        rows = raw_daily(symbol, start, end)
        return [rows[0], dict(rows[0], date="2026-08-02")]
    adapter._daily = reversed_daily
    result, output, error = run_sync(monkeypatch, tmp_path, adapter, "--fetch")

    assert result == 3
    assert "sorted" in error.getvalue()

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
