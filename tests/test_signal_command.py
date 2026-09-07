"""Command-level tests for the signal workflow (issue #5)."""

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
    write_cache(symbol, "daily", cache_dir, rows, [DateSpan(start=closes[0][0], end=closes[-1][0])])


def seed_broker(
    cache_dir: Path,
    symbol: str,
    days: list[date],
    activity_by_day: dict[date, list[dict]] | None = None,
) -> None:
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
            summary=(activity_by_day or {}).get(day, default_activity),
            provenance=Provenance(
                source="sectors",
                retrieved_at=datetime(2026, 9, 2, 16, 0, 0, tzinfo=ZoneInfo("Asia/Jakarta")),
                schema_version="1",
            ),
        ).model_dump(mode="json")
        rows.append(row)
    write_cache(symbol, "broker", cache_dir, rows, [DateSpan(start=days[0], end=days[-1])])


def run_signal(monkeypatch, tmp_path: Path, *extra: str):
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    output, error = StringIO(), StringIO()
    result = main(
        ["signal", *extra],
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )
    return result, output, error


def test_signal_computes_mixed_wins_and_losses(monkeypatch, tmp_path):
    # Tracer bullet: 3 wins (+10%) and 2 losses (-10%) give p=0.6, R=1.0, EV=0.2.
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "99"),
            (date(2026, 8, 13), "108.9"),
            (date(2026, 8, 14), "98.01"),
            (date(2026, 8, 15), "107.811"),
        ],
    )
    seed_broker(
        cache_dir,
        "BBCA",
        [
            date(2026, 8, 10),
            date(2026, 8, 11),
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
        ],
    )

    result, output, error = run_signal(
        monkeypatch,
        tmp_path,
        "--market-date",
        "2026-08-15",
        "--lookback",
        "1",
        "--min-samples",
        "5",
    )

    assert result == 0, error.getvalue()
    assert error.getvalue() == ""
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["stage"] == "complete"
    assert complete["status"] == "ok"
    assert len(complete["candidates"]) == 1
    candidate = complete["candidates"][0]
    assert candidate["symbol"] == "BBCA"
    assert candidate["samples"] == 5
    assert candidate["win_prob"] == pytest.approx(0.6)
    assert candidate["avg_gain"] == pytest.approx(0.1)
    assert candidate["avg_loss"] == pytest.approx(0.1)
    assert candidate["reward_risk"] == pytest.approx(1.0)
    assert candidate["broker_ev"] == pytest.approx(0.2)
    assert candidate["momentum"] == pytest.approx(0.1)
    assert candidate["signal_score"] == pytest.approx(0.02)
    # Raw EV follows p * R - (1 - p), no winsorization.
    assert candidate["broker_ev"] == pytest.approx(
        candidate["win_prob"] * candidate["reward_risk"] - (1 - candidate["win_prob"])
    )
    assert candidate["signal_score"] == pytest.approx(
        candidate["momentum"] * candidate["broker_ev"]
    )


def test_signal_marks_no_loss_ineligible_with_infinite_reason(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "121"),
            (date(2026, 8, 13), "133.1"),
        ],
    )
    seed_broker(
        cache_dir, "BBCA", [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]
    )

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "3",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    assert len(complete["ineligible_reasons"]) == 1
    reason = complete["ineligible_reasons"][0]["reason"]
    assert "no losses" in reason and "infinite" in reason


def test_signal_all_losses_gives_negative_ev_and_eligible(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "130"),
            (date(2026, 8, 11), "120"),
            (date(2026, 8, 12), "110"),
            (date(2026, 8, 13), "121"),
        ],
    )
    # Only the two loss outcomes are sampled; the final +10% momentum step
    # is not a broker observation, keeping EV at all-losses.
    seed_broker(cache_dir, "BBCA", [date(2026, 8, 10), date(2026, 8, 11)])

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "2",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert len(complete["candidates"]) == 1
    candidate = complete["candidates"][0]
    # 2 losses, 0 wins: p=0, avg_gain=0, R=0, EV=-1.
    assert candidate["samples"] == 2
    assert candidate["win_prob"] == pytest.approx(0.0)
    assert candidate["avg_gain"] == pytest.approx(0.0)
    assert candidate["broker_ev"] == pytest.approx(-1.0)
    # Momentum 110 -> 121 = +10%, EV -1 => signal -0.1 (negative score case).
    assert candidate["signal_score"] == pytest.approx(-0.1)


def test_signal_all_flat_ineligible_with_explicit_reason(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "100"),
            (date(2026, 8, 12), "100"),
            (date(2026, 8, 13), "100"),
        ],
    )
    seed_broker(
        cache_dir, "BBCA", [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]
    )

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "3",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    assert "no wins and no losses" in complete["ineligible_reasons"][0]["reason"]


def test_signal_marks_insufficient_samples_ineligible(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 12), "100"),
            (date(2026, 8, 13), "110"),
            (date(2026, 8, 14), "121"),
        ],
    )
    seed_broker(cache_dir, "BBCA", [date(2026, 8, 12), date(2026, 8, 13)])

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-14", "--lookback", "1",
        "--min-samples", "5",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    reason = complete["ineligible_reasons"][0]["reason"]
    assert "insufficient broker samples" in reason
    assert "need 5, found 2" in reason


def test_signal_excludes_delayed_outcomes_not_yet_observable(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "99"),
            (date(2026, 8, 13), "108.9"),
            (date(2026, 8, 14), "98.01"),
        ],
    )
    # Observation on 08-13 has its outcome on 08-14 (observable at signal
    # date 08-14). Observation on 08-14 would need 08-15, not yet available.
    seed_broker(
        cache_dir,
        "BBCA",
        [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13), date(2026, 8, 14)],
    )

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-14", "--lookback", "1",
        "--min-samples", "4",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert len(complete["candidates"]) == 1
    candidate = complete["candidates"][0]
    # Only 4 observable outcomes (08-14 excluded as delayed): 2 wins, 2 losses.
    assert candidate["samples"] == 4
    assert candidate["win_prob"] == pytest.approx(0.5)
    assert candidate["broker_ev"] == pytest.approx(0.0)
    assert candidate["signal_score"] == pytest.approx(0.0)


def test_signal_sorts_descending_breaks_ties_by_symbol_and_highlights_top(
    monkeypatch, tmp_path
):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "ASII", "TLKM"], date(2026, 8, 1))
    # BBCA and ASII share identical momentum (+10%) and EV histories
    # (1 win +10%, 1 loss -10% => EV 0? no - need positive EV for tie).
    # Use 2 wins +10% and 1 loss -10%: p=2/3, R=1, EV=1/3.
    for symbol in ("BBCA", "ASII"):
        seed_daily(
            cache_dir,
            symbol,
            [
                (date(2026, 8, 10), "100"),
                (date(2026, 8, 11), "110"),
                (date(2026, 8, 12), "99"),
                (date(2026, 8, 13), "108.9"),
            ],
        )
        seed_broker(
            cache_dir, symbol, [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]
        )
    # TLKM: negative momentum (-10%) with positive EV => negative signal, ranked last.
    # Extra early date keeps EV positive (2W/1L) while the final step is negative.
    seed_daily(
        cache_dir,
        "TLKM",
        [
            (date(2026, 8, 9), "100"),
            (date(2026, 8, 10), "110"),
            (date(2026, 8, 11), "99"),
            (date(2026, 8, 12), "108.9"),
            (date(2026, 8, 13), "98.01"),
        ],
    )
    seed_broker(
        cache_dir, "TLKM", [date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 11)]
    )

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "3",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    symbols = [c["symbol"] for c in complete["candidates"]]
    # BBCA and ASII tie on signal; symbol order breaks the tie deterministically.
    # TLKM negative signal sorts last.
    assert symbols == ["ASII", "BBCA", "TLKM"]
    by_symbol = {c["symbol"]: c for c in complete["candidates"]}
    assert by_symbol["ASII"]["signal_score"] == pytest.approx(by_symbol["BBCA"]["signal_score"])
    assert by_symbol["TLKM"]["signal_score"] < 0
    # Composite is Momentum x Broker EV and ranking is descending.
    scores = [c["signal_score"] for c in complete["candidates"]]
    assert scores == sorted(scores, reverse=True)
    for c in complete["candidates"]:
        assert c["signal_score"] == pytest.approx(c["momentum"] * c["broker_ev"])
    # Highest eligible highlighted as research only, no buy/sell instruction.
    highlight = complete["highlight"]
    assert highlight["symbol"] == "ASII"
    assert highlight["signal_score"] == pytest.approx(by_symbol["ASII"]["signal_score"])
    assert "research" in highlight["note"].lower()
    assert "not a buy" in highlight["note"].lower()
    assert "buy ASII" not in output.getvalue()
    assert "sell" not in highlight["note"].lower().replace("not a buy or sell", "")


def test_signal_marks_missing_broker_and_invalid_price_ineligible(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA", "TLKM"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [(date(2026, 8, 12), "100"), (date(2026, 8, 13), "110")],
    )
    # BBCA has no broker cache file at all.
    seed_daily(
        cache_dir,
        "TLKM",
        [(date(2026, 8, 12), "0"), (date(2026, 8, 13), "110")],
    )
    seed_broker(cache_dir, "TLKM", [date(2026, 8, 12)])

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "1",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    assert complete["highlight"] is None
    by_symbol = {r["symbol"]: r["reason"] for r in complete["ineligible_reasons"]}
    assert "no broker observations" in by_symbol["BBCA"]
    assert "invalid price" in by_symbol["TLKM"]


def test_signal_ignores_prices_after_market_date(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "99"),
            (date(2026, 8, 13), "108.9"),
            (date(2026, 8, 14), "1000"),
        ],
    )
    seed_broker(
        cache_dir, "BBCA", [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]
    )

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "3",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    candidate = complete["candidates"][0]
    assert candidate["end_close"] == "108.9"
    assert candidate["samples"] == 3


def test_signal_does_not_winsorize_extreme_returns(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "200"),
            (date(2026, 8, 12), "180"),
            (date(2026, 8, 13), "198"),
        ],
    )
    seed_broker(
        cache_dir, "BBCA", [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]
    )

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "3",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    candidate = complete["candidates"][0]
    # Raw +100% win kept as-is: avg_gain 0.55, avg_loss 0.1, R 5.5.
    assert candidate["avg_gain"] == pytest.approx(0.55)
    assert candidate["avg_loss"] == pytest.approx(0.1)
    assert candidate["reward_risk"] == pytest.approx(5.5)
    assert candidate["broker_ev"] == pytest.approx((2 / 3) * 5.5 - (1 / 3))


def test_signal_rejects_invalid_args_and_missing_universe(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(cache_dir, "BBCA", [(date(2026, 8, 13), "100")])

    result, _, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "0",
        "--min-samples", "3",
    )
    assert result == 1
    assert "--lookback" in error.getvalue()

    result, _, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-13", "--lookback", "1",
        "--min-samples", "0",
    )
    assert result == 1
    assert "--min-samples" in error.getvalue()

    result, _, error = run_signal(monkeypatch, tmp_path, "--market-date", "2026-09-03")
    assert result == 1
    assert "future" in error.getvalue()

    # Missing universe membership fails visibly instead of silent zeros.
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "empty-cache"))
    output, err2 = StringIO(), StringIO()
    from main import main as run_main

    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    code = run_main(
        ["signal", "--market-date", "2026-08-13"],
        stdout=output, stderr=err2, today=lambda: date(2026, 9, 2),
    )
    assert code == 1
    assert "no cached membership" in err2.getvalue()


def test_signal_excludes_non_buy_broker_days_from_ev_samples(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "99"),
            (date(2026, 8, 13), "89.1"),
        ],
    )
    sell_only = [
        {
            "broker_code": "MIR",
            "bfreq": 1,
            "blot": 0,
            "bval": "0",
            "bavg_per_share": None,
            "sfreq": 1,
            "slot": 1,
            "sval": "100",
            "savg_per_share": "100",
            "nlot": -1,
            "nval": "-100",
            "navg_per_share": "100",
        }
    ]
    seed_broker(
        cache_dir,
        "BBCA",
        [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)],
        {date(2026, 8, 11): sell_only},
    )

    result, output, error = run_signal(
        monkeypatch,
        tmp_path,
        "--market-date",
        "2026-08-13",
        "--lookback",
        "1",
        "--min-samples",
        "2",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert len(complete["candidates"]) == 1
    assert complete["candidates"][0]["samples"] == 2


def test_signal_marks_invalid_ev_history_ineligible(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 9), "0"),
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "121"),
        ],
    )
    seed_broker(
        cache_dir, "BBCA", [date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 11)]
    )

    result, output, error = run_signal(
        monkeypatch, tmp_path, "--market-date", "2026-08-12", "--lookback", "1",
        "--min-samples", "2",
    )

    assert result == 0, error.getvalue()
    complete = [json.loads(line) for line in output.getvalue().splitlines()][-1]
    assert complete["candidates"] == []
    assert "invalid price" in complete["ineligible_reasons"][0]["reason"]
