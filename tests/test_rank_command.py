"""Command-level tests for the rank workflow (issue #4)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from main import main
from kim_sectors.market_data.cache import write_cache
from kim_sectors.market_data.models import CachedDailyBar, DateSpan, Provenance, UniverseMembership


def seed_universe(cache_dir: Path, symbols: list[str], effective_date: date) -> None:
    from kim_sectors.market_data.cache import save_universe_membership

    membership = UniverseMembership(
        index="lq45",
        symbols=symbols,
        pages=1,
        effective_date=effective_date,
        resolved_at=datetime(2026, 9, 2, 16, 0, 0, tzinfo=ZoneInfo("Asia/Jakarta")),
        source="sectors",
        schema_version="1",
    )
    save_universe_membership(cache_dir, membership)


def seed_daily(cache_dir: Path, symbol: str, closes: list[tuple[date, str]]) -> None:
    rows = []
    for day, close in closes:
        row = CachedDailyBar(
            symbol=symbol,
            date=day,
            close=Decimal(close),
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            volume=1000000,
            market_cap=Decimal("100000000000"),
            provenance=Provenance(
                source="sectors",
                retrieved_at=datetime(2026, 9, 2, 16, 0, 0, tzinfo=ZoneInfo("Asia/Jakarta")),
                schema_version="1",
            ),
        ).model_dump(mode="json")
        rows.append(row)
    start = closes[0][0]
    end = closes[-1][0]
    write_cache(symbol, "daily", cache_dir, rows, [DateSpan(start=start, end=end)])


def run_rank(monkeypatch, tmp_path: Path, *extra: str):
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    output, error = StringIO(), StringIO()
    result = main(
        ["rank", *extra],
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )
    return result, output, error


def test_rank_sorts_known_returns_highest_first(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "TLKM"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [(date(2026, 8, 13), "100"), (date(2026, 8, 14), "110"), (date(2026, 8, 15), "121")],
    )
    seed_daily(
        cache_dir,
        "TLKM",
        [(date(2026, 8, 13), "100"), (date(2026, 8, 14), "100"), (date(2026, 8, 15), "100")],
    )

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "2"
    )

    assert result == 0, error.getvalue()
    assert error.getvalue() == ""
    stages = [json.loads(line) for line in output.getvalue().splitlines()]
    complete = stages[-1]
    assert complete["stage"] == "complete"
    assert complete["status"] == "ok"
    candidates = complete["candidates"]
    assert [c["symbol"] for c in candidates] == ["BBCA", "TLKM"]
    assert candidates[0]["momentum"] == 0.21
    assert candidates[1]["momentum"] == 0.0
    assert candidates[0]["market_date"] == "2026-08-15"
    assert candidates[0]["start_close"] == "100"
    assert candidates[0]["end_close"] == "121"


def test_rank_skips_non_trading_day_gaps(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    # Gap over weekend: Fri 14th -> Tue 18th, no Sat/Sun/Mon rows.
    seed_daily(
        cache_dir,
        "BBCA",
        [(date(2026, 8, 13), "100"), (date(2026, 8, 14), "100"), (date(2026, 8, 18), "110")],
    )

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-18", "--lookback", "2"
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"][0]["momentum"] == 0.1
    assert complete["candidates"][0]["start_date"] == "2026-08-13"
    assert complete["candidates"][0]["end_date"] == "2026-08-18"


def test_rank_marks_insufficient_history_ineligible(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(cache_dir, "BBCA", [(date(2026, 8, 15), "100")])

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "2"
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    assert len(complete["ineligible_reasons"]) == 1
    reason = complete["ineligible_reasons"][0]
    assert reason["symbol"] == "BBCA"
    assert "insufficient history" in reason["reason"]


def test_rank_marks_invalid_price_ineligible(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [(date(2026, 8, 13), "0"), (date(2026, 8, 14), "100"), (date(2026, 8, 15), "110")],
    )

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "2"
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    assert "invalid price" in complete["ineligible_reasons"][0]["reason"]


def test_rank_marks_missing_market_date_ineligible(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [(date(2026, 8, 13), "100"), (date(2026, 8, 14), "110")],
    )

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "1"
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    assert "no price on market date" in complete["ineligible_reasons"][0]["reason"]


def test_rank_sorts_negative_returns_descending_and_preserves_fields(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "TLKM", "ASII"], date(2026, 8, 1))
    seed_daily(
        cache_dir, "BBCA", [(date(2026, 8, 14), "100"), (date(2026, 8, 15), "110")]
    )
    seed_daily(
        cache_dir, "TLKM", [(date(2026, 8, 14), "100"), (date(2026, 8, 15), "90")]
    )
    seed_daily(
        cache_dir, "ASII", [(date(2026, 8, 14), "200"), (date(2026, 8, 15), "200")]
    )

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "1"
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    symbols = [c["symbol"] for c in complete["candidates"]]
    assert symbols == ["BBCA", "ASII", "TLKM"]
    by_symbol = {c["symbol"]: c for c in complete["candidates"]}
    assert by_symbol["BBCA"]["momentum"] == 0.1
    assert by_symbol["TLKM"]["momentum"] == -0.1
    # Preserved supporting input fields.
    for symbol in symbols:
        candidate = by_symbol[symbol]
        assert candidate["market_date"] == "2026-08-15"
        assert candidate["start_date"] == "2026-08-14"
        assert candidate["end_date"] == "2026-08-15"
        assert candidate["lookback"] == 1
        assert "start_close" in candidate and "end_close" in candidate


def test_rank_defaults_to_monthly_lookback_21(monkeypatch, tmp_path):
    from datetime import timedelta

    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 7, 1))
    base = date(2026, 7, 15)
    closes = [(base + timedelta(days=i), "100") for i in range(21)]
    closes.append((base + timedelta(days=21), "121"))
    seed_daily(cache_dir, "BBCA", closes)

    # No --lookback flag: monthly default must apply without a new script.
    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", (base + timedelta(days=21)).isoformat()
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["lookback"] == 21
    assert complete["candidates"][0]["momentum"] == 0.21


def test_rank_rejects_invalid_lookback_and_future_date(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(cache_dir, "BBCA", [(date(2026, 8, 15), "100")])

    result, _, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "0"
    )
    assert result == 1
    assert "--lookback" in error.getvalue()

    result, _, error = run_rank(monkeypatch, tmp_path, "--market-date", "2026-09-03")
    assert result == 1
    assert "future" in error.getvalue()


def test_rank_requires_cached_universe(monkeypatch, tmp_path):
    result, _, error = run_rank(monkeypatch, tmp_path, "--market-date", "2026-08-15")

    assert result == 1
    assert "no cached membership" in error.getvalue()


def test_rank_uses_universe_effective_on_market_date(monkeypatch, tmp_path):
    from kim_sectors.market_data.cache import save_universe_membership

    cache_dir = tmp_path / "cache"
    tz = ZoneInfo("Asia/Jakarta")
    save_universe_membership(
        cache_dir,
        UniverseMembership(
            index="lq45",
            symbols=["BBCA"],
            pages=1,
            effective_date=date(2026, 8, 1),
            resolved_at=datetime(2026, 8, 2, 16, 0, 0, tzinfo=tz),
            source="sectors",
            schema_version="1",
        ),
    )
    save_universe_membership(
        cache_dir,
        UniverseMembership(
            index="lq45",
            symbols=["TLKM"],
            pages=1,
            effective_date=date(2026, 8, 20),
            resolved_at=datetime(2026, 8, 21, 16, 0, 0, tzinfo=tz),
            source="sectors",
            schema_version="1",
        ),
    )
    seed_daily(
        cache_dir, "BBCA", [(date(2026, 8, 14), "100"), (date(2026, 8, 15), "110")]
    )
    seed_daily(
        cache_dir, "TLKM", [(date(2026, 8, 14), "100"), (date(2026, 8, 15), "110")]
    )

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "1"
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert [c["symbol"] for c in complete["candidates"]] == ["BBCA"]


def test_rank_ignores_prices_after_market_date(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 14), "100"),
            (date(2026, 8, 15), "110"),
            (date(2026, 8, 16), "1000"),
        ],
    )

    result, output, error = run_rank(
        monkeypatch, tmp_path, "--market-date", "2026-08-15", "--lookback", "1"
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"][0]["momentum"] == 0.1
    assert complete["candidates"][0]["end_close"] == "110"
