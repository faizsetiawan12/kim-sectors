from __future__ import annotations

from datetime import date
from io import StringIO

from main import main
from kim_sectors.market_data import InMemorySectorsAdapter


def test_sync_cache_rejects_future_end_date(monkeypatch, tmp_path):
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    error = StringIO()

    assert main(
        ["sync-cache", "--start", "2026-09-01", "--end", "2026-09-03"],
        build_market_data=lambda _config: InMemorySectorsAdapter(),
        stdout=StringIO(),
        stderr=error,
        today=lambda: date(2026, 9, 2),
    ) == 1
    assert "future" in error.getvalue()


def test_sync_cache_reports_corrupt_cache(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    (cache_dir / "universe").mkdir(parents=True)
    (cache_dir / "universe" / "lq45.json").write_text("not-json")
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(cache_dir))
    error = StringIO()

    assert main(
        ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-03"],
        build_market_data=lambda _config: InMemorySectorsAdapter(),
        stdout=StringIO(),
        stderr=error,
        today=lambda: date(2026, 9, 2),
    ) == 1
    assert "Cannot read universe cache" in error.getvalue()


def test_sync_cache_rejects_mismatched_broker_range(monkeypatch, tmp_path):
    adapter = InMemorySectorsAdapter(
        universe=["BBCA"],
        daily=lambda symbol, start, end: [],
        broker_summary=lambda symbol, start, end: {
            "symbol": symbol,
            "start": "2026-08-02",
            "end": "2026-08-03",
            "data": [],
        },
    )
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    error = StringIO()

    assert main(
        ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-03", "--fetch"],
        build_market_data=lambda _config: adapter,
        stdout=StringIO(),
        stderr=error,
        today=lambda: date(2026, 9, 2),
    ) == 3
    assert "range" in error.getvalue()


def test_sync_cache_empty_universe_is_schema_failure(monkeypatch, tmp_path):
    adapter = InMemorySectorsAdapter(universe=[])
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    error = StringIO()

    assert main(
        ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-03", "--fetch"],
        build_market_data=lambda _config: adapter,
        stdout=StringIO(),
        stderr=error,
        today=lambda: date(2026, 9, 2),
    ) == 3
    assert "empty symbol list" in error.getvalue()
