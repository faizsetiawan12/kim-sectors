"""Command-level tests for the backtest workflow (issue #7)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from main import main
from kim_sectors.market_data.cache import write_cache
from kim_sectors.market_data.models import (
    CachedBrokerSummaryDay,
    CachedDailyBar,
    DateSpan,
    Provenance,
    UniverseMembership,
)


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


def seed_daily(
    cache_dir: Path, symbol: str, closes: list[tuple[date, str]], *, span: DateSpan
) -> None:
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
    write_cache(symbol, "daily", cache_dir, rows, [span])


def seed_broker(cache_dir: Path, symbol: str, days: list[date], *, span: DateSpan) -> None:
    rows = []
    default_activity = [
        {
            "broker_code": "MIR",
            "bfreq": 1,
            "blot": 1,
            "bval": "100",
            "bavg_per_share": "100",
            "sfreq": 1,
            "slot": 1,
            "sval": "50",
            "savg_per_share": "50",
            "nlot": 1,
            "nval": "50",
            "navg_per_share": "50",
        }
    ]
    for day in days:
        row = CachedBrokerSummaryDay(
            symbol=symbol,
            date=day,
            summary=default_activity,
            provenance=Provenance(
                source="sectors",
                retrieved_at=datetime(2026, 9, 2, 16, 0, 0, tzinfo=ZoneInfo("Asia/Jakarta")),
                schema_version="1",
            ),
        ).model_dump(mode="json")
        rows.append(row)
    write_cache(symbol, "broker", cache_dir, rows, [span])

def run_backtest(monkeypatch, tmp_path: Path, *extra: str):
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "reports"))
    output, error = StringIO(), StringIO()
    result = main(
        ["run-backtest", *extra],
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )
    return result, output, error


def load_artifact(tmp_path: Path) -> dict:
    reports = tmp_path / "reports"
    files = sorted(reports.glob("backtest_*.json"))
    assert files, f"no backtest artifact under {reports}"
    return json.loads(files[-1].read_text())


# Shared daily history: 3 wins / 2 losses of +-10% observable by 2026-08-10.
def seed_win_loss_history(cache_dir: Path, symbol: str) -> None:
    seed_daily(
        cache_dir,
        symbol,
        [
            (date(2026, 8, 3), "100"),
            (date(2026, 8, 4), "110"),
            (date(2026, 8, 5), "99"),
            (date(2026, 8, 6), "108.9"),
            (date(2026, 8, 7), "98.01"),
            (date(2026, 8, 10), "107.811"),
            (date(2026, 8, 11), "118.5921"),
            (date(2026, 8, 12), "106.73289"),
        ],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )
    seed_broker(
        cache_dir,
        symbol,
        [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )


def test_backtest_reports_incomplete_coverage_before_calculating(monkeypatch, tmp_path):
    # Tracer bullet: coverage is gated before any signal math. Broker cache is
    # absent, so the window is not covered and the run must not calculate.
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [(date(2026, 8, 10), "100"), (date(2026, 8, 11), "110")],
        span=DateSpan(start=date(2026, 8, 10), end=date(2026, 8, 11)),
    )

    result, output, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-08-11"
    )

    assert result == 1
    assert "coverage incomplete" in error.getvalue()
    assert "sync-cache" in error.getvalue()
    assert "BBCA" in error.getvalue()
    # Missing history is reported; no artifact is written for an incomplete run.
    assert not list((tmp_path / "reports").glob("backtest_*.json"))


def test_backtest_tracer_enters_next_session_and_metrics(monkeypatch, tmp_path):
    # One symbol, one rebalance per session, zero costs. Signal on 08-10
    # (EV 0.2, momentum +0.10) enters at the NEXT session close on 08-11
    # (118.5921); the position then falls 10% to 08-12.
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_win_loss_history(cache_dir, "BBCA")

    result, output, error = run_backtest(
        monkeypatch,
        tmp_path,
        "--start", "2026-08-10", "--end", "2026-08-12",
        "--lookback", "1", "--min-samples", "1",
        "--top-k", "1", "--rebalance-sessions", "1",
        "--cost-bps", "0", "--slippage-bps", "0",
    )

    assert result == 0, error.getvalue()
    report = load_artifact(tmp_path)

    config = report["config"]
    assert config["universe"] == "lq45"
    assert config["start"] == "2026-08-10"
    assert config["end"] == "2026-08-12"
    assert config["lookback"] == 1
    assert config["min_samples"] == 1
    assert config["top_k"] == 1
    assert config["rebalance_sessions"] == 1
    assert config["cost_bps"] == 0
    assert config["slippage_bps"] == 0
    assert config["starting_capital"] == 1_000_000.0
    assert config["universe_effective_date"] == "2026-08-01"
    assert "next eligible market session" in config["entry_timing"]

    assert report["status"] == "ok"
    assert report["coverage"]["status"] == "ok"

    # Entry at the next eligible session: no trade on the signal date itself.
    assert report["trades_detail"] == [
        {
            "date": "2026-08-11",
            "signal_date": "2026-08-10",
            "symbol": "BBCA",
            "side": "buy",
            "price": pytest.approx(118.5921),
            "quantity": pytest.approx(1_000_000.0 / 118.5921),
            "notional": pytest.approx(1_000_000.0),
            "cost": 0.0,
            "slippage": 0.0,
            "note": None,
        }
    ]
    assert report["trades"] == 1

    # Equity: flat on 08-10 and 08-11 (bought at close), -10% to 08-12.
    curve = {point["date"]: point["value"] for point in report["equity_curve"]}
    assert curve["2026-08-10"] == pytest.approx(1_000_000.0)
    assert curve["2026-08-11"] == pytest.approx(1_000_000.0)
    assert curve["2026-08-12"] == pytest.approx(900_000.0)
    assert report["total_return"] == pytest.approx(-0.10)

    # One holding period (08-11 -> 08-12): win rate 0, average period -10%.
    assert report["period_returns"] == [
        {"start_date": "2026-08-11", "end_date": "2026-08-12", "value": pytest.approx(-0.10)}
    ]
    assert report["win_rate"] == pytest.approx(0.0)
    assert report["average_period_return"] == pytest.approx(-0.10)
    assert report["max_drawdown"] == pytest.approx(-0.10)

    # Observation counts: one eligible candidate per signal date (08-10, 08-11,
    # 08-12), one executed rebalance per session, three signals total.
    assert report["observations"] == 3
    assert report["ineligible_observations"] == 0
    assert report["rebalances"] == 3
    first, second, third = report["rebalance_events"]
    assert first["signal_date"] == "2026-08-10" and first["entry_date"] == "2026-08-11"
    assert first["target"] == ["BBCA"]
    assert second["signal_date"] == "2026-08-11" and second["entry_date"] == "2026-08-12"
    assert third["signal_date"] == "2026-08-12" and third["entry_date"] is None
    assert "no next market session" in third["note"]

    # Benchmark: equal-weight buy-and-hold of the universe, -1% endpoint close.
    benchmark = report["benchmark"]
    assert benchmark["total_return"] == pytest.approx(-0.01)
    assert "equal-weight buy-and-hold" in benchmark["label"]
    assert "1/1" in benchmark["note"]


def test_backtest_selects_top_k_and_breaks_ties_by_symbol(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "ASII", "TLKM"], date(2026, 8, 1))
    # BBCA and ASII tie for the top signal; TLKM is lower. Two of three held.
    for symbol in ("BBCA", "ASII"):
        seed_daily(
            cache_dir,
            symbol,
            [
                (date(2026, 8, 10), "100"),
                (date(2026, 8, 11), "110"),
                (date(2026, 8, 12), "99"),
                (date(2026, 8, 13), "108.9"),
                (date(2026, 8, 14), "119.79"),
                (date(2026, 8, 15), "131.769"),
            ],
            span=DateSpan(start=date(2026, 8, 10), end=date(2026, 8, 15)),
        )
        seed_broker(
            cache_dir,
            symbol,
            [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13), date(2026, 8, 14), date(2026, 8, 15)],
            span=DateSpan(start=date(2026, 8, 10), end=date(2026, 8, 15)),
        )
    seed_daily(
        cache_dir,
        "TLKM",
        [
            (date(2026, 8, 9), "100"),
            (date(2026, 8, 10), "110"),
            (date(2026, 8, 11), "99"),
            (date(2026, 8, 12), "108.9"),
            (date(2026, 8, 13), "98.01"),
            (date(2026, 8, 14), "107.811"),
            (date(2026, 8, 15), "118.5921"),
        ],
        span=DateSpan(start=date(2026, 8, 9), end=date(2026, 8, 15)),
    )
    seed_broker(
        cache_dir,
        "TLKM",
        [date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13), date(2026, 8, 14), date(2026, 8, 15)],
        span=DateSpan(start=date(2026, 8, 9), end=date(2026, 8, 15)),
    )

    result, output, error = run_backtest(
        monkeypatch,
        tmp_path,
        "--start", "2026-08-13", "--end", "2026-08-15",
        "--lookback", "1", "--min-samples", "3",
        "--top-k", "2", "--rebalance-sessions", "1",
        "--cost-bps", "0", "--slippage-bps", "0",
    )

    assert result == 0, error.getvalue()
    report = load_artifact(tmp_path)

    first = report["rebalance_events"][0]
    assert first["target"] == ["ASII", "BBCA"]
    assert first["eligible"] == 3
    buys = [t for t in report["trades_detail"] if t["side"] == "buy"]
    assert [t["symbol"] for t in buys] == ["ASII", "BBCA"]
    assert buys[0]["notional"] == pytest.approx(500_000.0)
    assert buys[1]["notional"] == pytest.approx(500_000.0)
    assert not any(t["symbol"] == "TLKM" for t in report["trades_detail"])
    # Both positions rise 10% to the final session: +10% total return.
    assert report["total_return"] == pytest.approx(0.10)
    assert report["period_returns"][-1]["value"] == pytest.approx(0.10)


def test_backtest_rebalances_holdings_on_schedule(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "ASII"], date(2026, 8, 1))
    # BBCA leads on 08-10; ASII overtakes by 08-11, forcing a swap.
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 3), "100"),
            (date(2026, 8, 4), "110"),
            (date(2026, 8, 5), "99"),
            (date(2026, 8, 6), "108.9"),
            (date(2026, 8, 7), "98.01"),
            (date(2026, 8, 10), "107.811"),
            (date(2026, 8, 11), "118.5921"),
            (date(2026, 8, 12), "106.73289"),
        ],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )
    seed_daily(
        cache_dir,
        "ASII",
        [
            (date(2026, 8, 3), "100"),
            (date(2026, 8, 4), "110"),
            (date(2026, 8, 5), "99"),
            (date(2026, 8, 6), "108.9"),
            (date(2026, 8, 7), "98.01"),
            (date(2026, 8, 10), "98.01"),
            (date(2026, 8, 11), "117.612"),
            (date(2026, 8, 12), "105.8508"),
        ],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )
    for symbol in ("BBCA", "ASII"):
        seed_broker(
            cache_dir,
            symbol,
            [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)],
            span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
        )

    result, output, error = run_backtest(
        monkeypatch,
        tmp_path,
        "--start", "2026-08-10", "--end", "2026-08-12",
        "--lookback", "1", "--min-samples", "1",
        "--top-k", "1", "--rebalance-sessions", "1",
        "--cost-bps", "0", "--slippage-bps", "0",
    )

    assert result == 0, error.getvalue()
    report = load_artifact(tmp_path)

    first, second = report["rebalance_events"][:2]
    assert first["target"] == ["BBCA"]
    assert first["entry_date"] == "2026-08-11"
    assert second["target"] == ["ASII"]
    assert second["entry_date"] == "2026-08-12"

    sides = [(t["symbol"], t["side"], t["date"]) for t in report["trades_detail"]]
    assert sides == [
        ("BBCA", "buy", "2026-08-11"),
        ("BBCA", "sell", "2026-08-12"),
        ("ASII", "buy", "2026-08-12"),
    ]
    assert report["trades"] == 3
    # The swap realizes the -10% move on BBCA, then parks in ASII at close.
    assert report["total_return"] == pytest.approx(-0.10)
    assert report["period_returns"] == [
        {"start_date": "2026-08-11", "end_date": "2026-08-12", "value": pytest.approx(-0.10)}
    ]


def test_backtest_applies_costs_and_slippage_to_trades(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_win_loss_history(cache_dir, "BBCA")

    result, output, error = run_backtest(
        monkeypatch,
        tmp_path,
        "--start", "2026-08-10", "--end", "2026-08-12",
        "--lookback", "1", "--min-samples", "1",
        "--top-k", "1", "--rebalance-sessions", "1",
        "--cost-bps", "100", "--slippage-bps", "50",
    )

    assert result == 0, error.getvalue()
    report = load_artifact(tmp_path)

    buy = report["trades_detail"][0]
    assert buy["cost"] == pytest.approx(1_000_000.0 * 100 / 10_000)
    assert buy["slippage"] == pytest.approx(1_000_000.0 * 50 / 10_000)
    assert buy["notional"] == pytest.approx(985_000.0)
    # 1.5% total drag on the entry; position then falls 10%.
    assert report["total_return"] == pytest.approx(0.985 * 0.9 - 1.0)
    assert report["config"]["cost_bps"] == 100
    assert report["config"]["slippage_bps"] == 50


def test_backtest_point_in_time_excludes_unobservable_outcomes(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["ASII", "BBCA"], date(2026, 8, 1))
    # Identical prices for both. ASII and BBCA tie on 08-10 at 3W/2L (EV 0.2),
    # so the symbol tie-break picks ASII. BBCA additionally has a broker
    # observation on 08-10 whose outcome (08-11 close) is NOT observable by
    # 08-10; if it leaked into the calibration, BBCA would rank first instead.
    for symbol in ("ASII", "BBCA"):
        seed_daily(
            cache_dir,
            symbol,
            [
                (date(2026, 8, 3), "100"),
                (date(2026, 8, 4), "110"),
                (date(2026, 8, 5), "99"),
                (date(2026, 8, 6), "108.9"),
                (date(2026, 8, 7), "98.01"),
                (date(2026, 8, 10), "107.811"),
                (date(2026, 8, 11), "118.5921"),
                (date(2026, 8, 12), "106.73289"),
            ],
            span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
        )
    seed_broker(
        cache_dir,
        "ASII",
        [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )
    seed_broker(
        cache_dir,
        "BBCA",
        [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )

    result, output, error = run_backtest(
        monkeypatch,
        tmp_path,
        "--start", "2026-08-10", "--end", "2026-08-12",
        "--lookback", "1", "--min-samples", "1",
        "--top-k", "1", "--rebalance-sessions", "2",
        "--cost-bps", "0", "--slippage-bps", "0",
    )

    assert result == 0, error.getvalue()
    report = load_artifact(tmp_path)

    first = report["rebalance_events"][0]
    assert first["signal_date"] == "2026-08-10"
    assert first["target"] == ["ASII"]
    assert first["eligible"] == 2
    # Only the observable outcome set feeds the calibration, so BBCA's delayed
    # 08-10 observation does not flip the selection to BBCA.
    assert [t["symbol"] for t in report["trades_detail"]] == ["ASII"]
    assert report["trades_detail"][0]["signal_date"] == "2026-08-10"
    assert report["trades_detail"][0]["date"] == "2026-08-11"
    assert report["trades_detail"][0]["price"] == pytest.approx(118.5921)


def test_backtest_skips_entry_when_next_session_price_missing(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "ASII"], date(2026, 8, 1))
    # BBCA ranks first on 08-10 but has no close on the next session 08-11,
    # so its entry is skipped and recorded; ASII (ranked second on 08-10,
    # first on 08-11) is entered instead on 08-12.
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 3), "100"),
            (date(2026, 8, 4), "110"),
            (date(2026, 8, 5), "99"),
            (date(2026, 8, 6), "108.9"),
            (date(2026, 8, 7), "98.01"),
            (date(2026, 8, 10), "107.811"),
            (date(2026, 8, 12), "106.73289"),
        ],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )
    seed_daily(
        cache_dir,
        "ASII",
        [
            (date(2026, 8, 3), "100"),
            (date(2026, 8, 4), "110"),
            (date(2026, 8, 5), "99"),
            (date(2026, 8, 6), "108.9"),
            (date(2026, 8, 7), "98.01"),
            (date(2026, 8, 10), "98.01"),
            (date(2026, 8, 11), "107.811"),
            (date(2026, 8, 12), "97.0299"),
        ],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
    )
    for symbol in ("BBCA", "ASII"):
        seed_broker(
            cache_dir,
            symbol,
            [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)],
            span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 12)),
        )

    result, output, error = run_backtest(
        monkeypatch,
        tmp_path,
        "--start", "2026-08-10", "--end", "2026-08-12",
        "--lookback", "1", "--min-samples", "1",
        "--top-k", "1", "--rebalance-sessions", "1",
        "--cost-bps", "0", "--slippage-bps", "0",
    )

    assert result == 0, error.getvalue()
    report = load_artifact(tmp_path)

    first = report["rebalance_events"][0]
    assert first["signal_date"] == "2026-08-10"
    assert first["target"] == ["BBCA"]
    assert first["skipped"] == ["BBCA"]
    assert not any(t["symbol"] == "BBCA" for t in report["trades_detail"])
    # ASII becomes the target on 08-11 and is entered on 08-12.
    second = report["rebalance_events"][1]
    assert second["target"] == ["ASII"]
    assert second["entry_date"] == "2026-08-12"
    assert report["trades_detail"] == [
        {
            "date": "2026-08-12",
            "signal_date": "2026-08-11",
            "symbol": "ASII",
            "side": "buy",
            "price": pytest.approx(97.0299),
            "quantity": pytest.approx(1_000_000.0 / 97.0299),
            "notional": pytest.approx(1_000_000.0),
            "cost": 0.0,
            "slippage": 0.0,
            "note": None,
        }
    ]


def test_backtest_empty_candidates_liquidates_to_cash(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "ASII"], date(2026, 8, 1))
    # BBCA qualifies on 08-10 and is entered on 08-11. On 08-12 BBCA has no
    # price and ASII has no losses in its broker history, so no candidates
    # exist; the portfolio liquidates to cash on 08-13.
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 3), "100"),
            (date(2026, 8, 4), "110"),
            (date(2026, 8, 5), "99"),
            (date(2026, 8, 6), "108.9"),
            (date(2026, 8, 7), "98.01"),
            (date(2026, 8, 10), "107.811"),
            (date(2026, 8, 11), "118.5921"),
            (date(2026, 8, 13), "106.73289"),
        ],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 13)),
    )
    seed_daily(
        cache_dir,
        "ASII",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "121"),
            (date(2026, 8, 13), "121"),
        ],
        span=DateSpan(start=date(2026, 8, 10), end=date(2026, 8, 13)),
    )
    seed_broker(
        cache_dir,
        "BBCA",
        [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)],
        span=DateSpan(start=date(2026, 8, 3), end=date(2026, 8, 13)),
    )
    seed_broker(
        cache_dir,
        "ASII",
        [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)],
        span=DateSpan(start=date(2026, 8, 10), end=date(2026, 8, 13)),
    )

    result, output, error = run_backtest(
        monkeypatch,
        tmp_path,
        "--start", "2026-08-10", "--end", "2026-08-13",
        "--lookback", "1", "--min-samples", "1",
        "--top-k", "1", "--rebalance-sessions", "2",
        "--cost-bps", "0", "--slippage-bps", "0",
    )

    assert result == 0, error.getvalue()
    report = load_artifact(tmp_path)

    first, second = report["rebalance_events"]
    assert first["target"] == ["BBCA"]
    assert second["signal_date"] == "2026-08-12"
    assert second["target"] == []
    assert second["eligible"] == 0
    assert second["ineligible"] == 2
    assert second["entry_date"] == "2026-08-13"

    sides = [(t["symbol"], t["side"], t["date"]) for t in report["trades_detail"]]
    assert sides == [
        ("BBCA", "buy", "2026-08-11"),
        ("BBCA", "sell", "2026-08-13"),
    ]
    # The liquidation realizes the -10% move from entry to final session.
    assert report["total_return"] == pytest.approx(-0.10)


def test_backtest_repeat_is_deterministic_and_makes_no_api_calls(monkeypatch, tmp_path):
    import main as main_module
    import kim_sectors.market_data.live as live

    def boom(*args, **kwargs):
        raise AssertionError("run-backtest must not call the Sectors API")

    # Any adapter construction anywhere in the command path would fail loudly:
    # the backtest must be pure cache reads.
    monkeypatch.setattr(live, "SectorsHttpAdapter", boom)
    monkeypatch.setattr(main_module, "SectorsHttpAdapter", boom)
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_win_loss_history(cache_dir, "BBCA")
    args = (
        "--start", "2026-08-10", "--end", "2026-08-12",
        "--lookback", "1", "--min-samples", "1",
        "--top-k", "1", "--rebalance-sessions", "1",
    )

    result, output, error = run_backtest(monkeypatch, tmp_path, *args)
    assert result == 0, error.getvalue()
    first_report = load_artifact(tmp_path)

    result, output, error = run_backtest(monkeypatch, tmp_path, *args)
    assert result == 0, error.getvalue()
    second_report = load_artifact(tmp_path)

    # Deterministic metrics and equity curve: only the generation timestamp may
    # differ between repeats.
    first_report.pop("generated_at")
    second_report.pop("generated_at")
    assert first_report == second_report


def test_backtest_rejects_invalid_arguments(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_win_loss_history(cache_dir, "BBCA")

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-12", "--end", "2026-08-10"
    )
    assert result == 1
    assert "--start" in error.getvalue()

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-09-03"
    )
    assert result == 1
    assert "future" in error.getvalue()

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-08-12", "--top-k", "0"
    )
    assert result == 1
    assert "--top-k" in error.getvalue()

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-08-12",
        "--rebalance-sessions", "0",
    )
    assert result == 1
    assert "--rebalance-sessions" in error.getvalue()

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-08-12", "--cost-bps", "-1"
    )
    assert result == 1
    assert "--cost-bps" in error.getvalue()

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-08-12",
        "--slippage-bps", "-1",
    )
    assert result == 1
    assert "--slippage-bps" in error.getvalue()

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-08-12", "--lookback", "0"
    )
    assert result == 1
    assert "--lookback" in error.getvalue()

    result, _, error = run_backtest(
        monkeypatch, tmp_path, "--start", "2026-08-10", "--end", "2026-08-12",
        "--min-samples", "0",
    )
    assert result == 1
    assert "--min-samples" in error.getvalue()

    # Missing universe membership fails visibly instead of silent zeros.
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "empty-cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "reports"))
    output, error = StringIO(), StringIO()
    code = main(
        ["run-backtest", "--start", "2026-08-10", "--end", "2026-08-12"],
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )
    assert code == 1
    assert "no cached membership" in error.getvalue()