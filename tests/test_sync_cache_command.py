from __future__ import annotations

import json
from datetime import date
from io import StringIO
from pathlib import Path

from main import main
from kim_sectors.market_data import InMemorySectorsAdapter

from .support import broker_summary_payload, daily_bars_payload


def make_adapter(symbols: list[str]) -> InMemorySectorsAdapter:
    return InMemorySectorsAdapter(
        universe=symbols,
        daily=lambda symbol, start, end: daily_bars_payload(symbol, start=start, end=end),
        broker_summary=lambda symbol, start, end: {
            **broker_summary_payload(symbol, start=start, end=end),
            "data": [
                {
                    "date": day.isoformat(),
                    "summary": [],
                }
                for day in [start, end]
            ],
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


def test_sync_cache_preview_does_not_call_market_data_or_write_cache(monkeypatch, tmp_path):
    adapter = make_adapter(["BBCA", "TLKM"])
    result, output, error = run_sync(monkeypatch, tmp_path, adapter)

    assert result == 0
    stages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert stages[0]["stage"] == "universe"
    assert stages[0]["status"] == "unresolved"
    assert stages[1]["stage"] == "plan"
    assert stages[1]["estimated_credits"] == 1
    assert stages[1]["market_credits_unknown"] is True
    assert stages[-1]["stage"] == "complete"
    assert stages[-1]["mode"] == "preview"
    assert adapter.calls == []
    assert error.getvalue() == ""
    assert not (tmp_path / "cache").exists()


def test_sync_cache_first_fetch_persists_provenance_and_reports_cost(monkeypatch, tmp_path):
    adapter = make_adapter(["BBCA"])
    result, output, error = run_sync(monkeypatch, tmp_path, adapter, "--fetch")

    assert result == 0
    assert error.getvalue() == ""
    assert [(call[0], call[1]) for call in adapter.calls] == [
        ("universe", "lq45"),
        ("daily", "BBCA"),
        ("broker-summary", "BBCA"),
    ]
    daily_path = tmp_path / "cache" / "daily" / "BBCA.json"
    broker_path = tmp_path / "cache" / "broker" / "BBCA.json"
    universe_path = tmp_path / "cache" / "universe" / "lq45.json"
    assert daily_path.exists() and broker_path.exists() and universe_path.exists()
    daily = json.loads(daily_path.read_text())
    assert daily["covered_spans"] == [{"start": "2026-08-01", "end": "2026-08-03"}]
    assert daily["rows"][0]["provenance"] == {
        "retrieved_at": daily["rows"][0]["provenance"]["retrieved_at"],
        "schema_version": "1",
        "source": "sectors",
    }
    assert daily["rows"][0]["symbol"] == "BBCA"
    assert json.loads(universe_path.read_text())[0]["effective_date"] == "2026-09-02"
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["credits_spent"] == 3


def test_sync_cache_repeat_uses_coverage_without_market_calls(monkeypatch, tmp_path):
    first = make_adapter(["BBCA"])
    assert run_sync(monkeypatch, tmp_path, first, "--fetch")[0] == 0

    second = make_adapter(["BBCA"])
    result, output, error = run_sync(monkeypatch, tmp_path, second, "--fetch")

    assert result == 0
    assert error.getvalue() == ""
    assert second.calls == []
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["credits_spent"] == 0


def test_sync_cache_preview_reuses_cached_universe(monkeypatch, tmp_path):
    adapter = make_adapter(["BBCA"])
    assert run_sync(monkeypatch, tmp_path, adapter, "--fetch")[0] == 0
    adapter.calls.clear()

    result, output, error = run_sync(monkeypatch, tmp_path, adapter)

    assert result == 0
    assert error.getvalue() == ""
    stages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert stages[0]["status"] == "reused"
    assert stages[1]["estimated_credits"] == 0
    assert adapter.calls == []


def test_sync_cache_incremental_extension_fetches_only_new_dates(monkeypatch, tmp_path):
    adapter = make_adapter(["BBCA"])
    assert run_sync(monkeypatch, tmp_path, adapter, "--fetch")[0] == 0
    adapter.calls.clear()

    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    assert main(
        ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-05", "--fetch"],
        build_market_data=lambda _config: adapter,
        stdout=StringIO(), stderr=StringIO(), today=lambda: date(2026, 9, 2),
    ) == 0
    assert adapter.calls == [
        ("daily", "BBCA", date(2026, 8, 4), date(2026, 8, 5)),
        ("broker-summary", "BBCA", date(2026, 8, 4), date(2026, 8, 5)),
    ]
