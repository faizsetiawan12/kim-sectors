"""Command-level tests for the run-daily workflow (issue #6).

The recorder adapter is the controlled notification seam: it records every
delivered message plus the artifact state on disk at send time, so tests can
verify that Markdown/JSON artifacts exist before any Telegram delivery attempt.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
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
from kim_sectors.outputs.telegram import TelegramDeliveryError


class RecordingTelegramSender:
    """Controlled Telegram adapter recording deliveries and artifact state."""

    def __init__(self, output_dir: Path, *, fail_with: Exception | None = None) -> None:
        self.output_dir = output_dir
        self.fail_with = fail_with
        # Each record is (text, markdown files present, json files present).
        self.messages: list[tuple[str, list[str], list[str]]] = []

    def send(self, text: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        daily_dir = self.output_dir / "daily"
        if daily_dir.exists():
            markdown = sorted(path.name for path in daily_dir.glob("*.md"))
            json_files = sorted(path.name for path in daily_dir.glob("*.json"))
        else:
            markdown = []
            json_files = []
        self.messages.append((text, markdown, json_files))


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


def seed_broker(cache_dir: Path, symbol: str, days: list[date]) -> None:
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
    write_cache(symbol, "broker", cache_dir, rows, [DateSpan(start=days[0], end=days[-1])])


def run_daily(monkeypatch, tmp_path: Path, recorder: RecordingTelegramSender, *extra: str, build_market_data=None):
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "reports"))
    output, error = StringIO(), StringIO()
    result = main(
        ["run-daily", *extra],
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
        build_market_data=build_market_data,
        build_telegram_sender=lambda _config: recorder,
    )
    return result, output, error


def mixed_daily_payload(symbol: str, start: date, end: date) -> list[dict]:
    """Daily bars with alternating +10%/-9.09% closes so EV mixes wins/losses."""
    rows = []
    for i in range((end - start).days + 1):
        day = date.fromordinal(start.toordinal() + i)
        close = 110.0 if i % 2 == 0 else 100.0
        rows.append(
            {
                "symbol": symbol,
                "date": day.isoformat(),
                "close": close,
                "open": close,
                "high": close,
                "low": close,
                "volume": 1000000,
                "market_cap": 100000000000.0,
            }
        )
    return rows


def broker_payload_for_span(symbol: str, start: date, end: date) -> dict:
    """Broker summary covering every date so chunk coverage is complete."""
    return {
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "data": [
            {
                "date": date.fromordinal(start.toordinal() + i).isoformat(),
                "summary": [
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
                ],
            }
            for i in range((end - start).days + 1)
        ],
    }


def test_daily_brief_replay_writes_artifacts_before_sending_executive(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    reports = tmp_path / "reports"
    seed_universe(cache_dir, ["BBCA", "TLKM"], date(2026, 8, 1))
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
    seed_daily(cache_dir, "TLKM", [(date(2026, 8, 14), "100"), (date(2026, 8, 15), "110")])
    recorder = RecordingTelegramSender(reports)

    result, output, error = run_daily(
        monkeypatch,
        tmp_path,
        recorder,
        "--market-date",
        "2026-08-15",
        "--lookback",
        "1",
        "--min-samples",
        "3",
    )

    assert result == 0, error.getvalue()
    assert error.getvalue() == ""
    markdown_path = reports / "daily" / "2026-08-15.md"
    json_path = reports / "daily" / "2026-08-15.json"
    assert markdown_path.exists()
    assert json_path.exists()
    assert len(recorder.messages) == 1
    text, markdown_present, json_present = recorder.messages[0]
    assert "2026-08-15.md" in markdown_present
    assert "2026-08-15.json" in json_present
    assert "KIM Daily Brief" in text
    assert "BBCA" in text
    assert "research and decision support only" in text.lower()


def test_daily_brief_artifacts_include_required_content(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    reports = tmp_path / "reports"
    seed_universe(cache_dir, ["BBCA", "TLKM"], date(2026, 8, 1))
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
    seed_daily(cache_dir, "TLKM", [(date(2026, 8, 14), "100"), (date(2026, 8, 15), "110")])
    recorder = RecordingTelegramSender(reports)

    result, output, error = run_daily(
        monkeypatch, tmp_path, recorder,
        "--market-date", "2026-08-15", "--lookback", "1", "--min-samples", "3",
    )

    assert result == 0, error.getvalue()
    json_path = reports / "daily" / "2026-08-15.json"
    markdown_path = reports / "daily" / "2026-08-15.md"
    payload = json.loads(json_path.read_text())

    # Market date and WIB run timestamp.
    assert payload["mode"] == "daily"
    assert payload["index"] == "lq45"
    assert payload["market_date"] == "2026-08-15"
    assert payload["timezone"] == "Asia/Jakarta"
    generated_at = datetime.fromisoformat(payload["generated_at"])
    assert generated_at.utcoffset() == timedelta(hours=7)

    # Data freshness from cache provenance.
    assert payload["freshness"] == {
        "market_date": "2026-08-15",
        "retrieved_at": "2026-09-02T16:00:00+07:00",
    }

    # Universe coverage.
    assert payload["universe"] == {
        "index": "lq45",
        "members": 2,
        "eligible": 1,
        "ineligible": 1,
    }

    # Ranked candidates with component values.
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["symbol"] == "BBCA"
    assert candidate["momentum"] == pytest.approx(0.1)
    assert candidate["win_prob"] == pytest.approx(0.6)
    assert candidate["avg_gain"] == pytest.approx(0.1)
    assert candidate["avg_loss"] == pytest.approx(0.1)
    assert candidate["reward_risk"] == pytest.approx(1.0)
    assert candidate["broker_ev"] == pytest.approx(0.2)
    assert candidate["signal_score"] == pytest.approx(0.02)
    assert candidate["signal_score"] == pytest.approx(
        candidate["momentum"] * candidate["broker_ev"]
    )

    # Exclusions and warnings.
    assert len(payload["ineligible"]) == 1
    assert payload["ineligible"][0]["symbol"] == "TLKM"
    assert "no broker observations" in payload["ineligible"][0]["reason"]

    # Research-only disclaimer.
    assert "research and decision support only" in payload["disclaimer"].lower()

    markdown = markdown_path.read_text()
    assert "# Daily Market Brief - LQ45" in markdown
    assert "**Market date**: 2026-08-15" in markdown
    assert "**Generated at**:" in markdown and "Asia/Jakarta" in markdown
    assert "**Data freshness**:" in markdown
    assert "2 members, 1 ranked, 1 excluded" in markdown
    assert "| 1 | BBCA |" in markdown
    assert "TLKM" in markdown
    assert "research and decision support only" in markdown.lower()


def test_daily_brief_live_run_fetches_then_scores_then_reports(monkeypatch, tmp_path):
    from kim_sectors.market_data.memory import InMemorySectorsAdapter

    reports = tmp_path / "reports"
    adapter = InMemorySectorsAdapter(
        universe=["BBCA", "TLKM"],
        daily=mixed_daily_payload,
        broker_summary=broker_payload_for_span,
    )
    recorder = RecordingTelegramSender(reports)

    # No --market-date: defaults to today (WIB), so the live fetch stage runs.
    result, output, error = run_daily(
        monkeypatch, tmp_path, recorder,
        build_market_data=lambda _config: adapter,
    )

    assert result == 0, error.getvalue()
    json_path = reports / "daily" / "2026-09-02.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["market_date"] == "2026-09-02"
    assert payload["universe"]["members"] == 2
    assert len(payload["candidates"]) == 2
    assert len(recorder.messages) == 1
    assert "KIM Daily Brief" in recorder.messages[0][0]
    # Fetch/validation ran end to end against the controlled adapter.
    call_kinds = [call[0] for call in adapter.calls]
    assert "universe" in call_kinds
    assert "daily" in call_kinds
    assert "broker-summary" in call_kinds
    stages = [json.loads(line)["stage"] for line in output.getvalue().splitlines()]
    assert "universe" in stages and "report" in stages and "notify" in stages
    assert stages[-1] == "complete"
    final = json.loads(output.getvalue().splitlines()[-1])
    assert final["mode"] == "daily"
    assert final["notify"] == "sent"


def test_daily_brief_telegram_failure_is_visible_and_artifacts_remain(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    reports = tmp_path / "reports"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(
        cache_dir,
        "BBCA",
        [
            (date(2026, 8, 10), "100"),
            (date(2026, 8, 11), "110"),
            (date(2026, 8, 12), "99"),
            (date(2026, 8, 13), "108.9"),
        ],
    )
    seed_broker(cache_dir, "BBCA", [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)])
    recorder = RecordingTelegramSender(
        reports, fail_with=TelegramDeliveryError("chat not found")
    )

    result, output, error = run_daily(
        monkeypatch,
        tmp_path,
        recorder,
        "--market-date",
        "2026-08-15",
        "--lookback",
        "1",
        "--min-samples",
        "3",
    )

    assert result == 5
    assert "telegram delivery failed" in error.getvalue()
    assert "chat not found" in error.getvalue()
    # Already-written artifacts remain available despite the delivery failure.
    assert (reports / "daily" / "2026-08-15.md").exists()
    assert (reports / "daily" / "2026-08-15.json").exists()
    assert recorder.messages == []
    # The failure is visible in the structured stage log too.
    notify_stage = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if json.loads(line).get("stage") == "notify"
    ]
    assert notify_stage and notify_stage[-1]["status"] == "error"


def test_daily_brief_without_telegram_config_skips_delivery(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    reports = tmp_path / "reports"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_daily(cache_dir, "BBCA", [(date(2026, 8, 12), "100"), (date(2026, 8, 13), "110")])
    seed_broker(cache_dir, "BBCA", [date(2026, 8, 12)])

    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "reports"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    output, error = StringIO(), StringIO()
    result = main(
        ["run-daily", "--market-date", "2026-08-13", "--lookback", "1", "--min-samples", "1"],
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )

    assert result == 0, error.getvalue()
    # Artifacts are still written even without Telegram configuration.
    assert (reports / "daily" / "2026-08-13.md").exists()
    assert (reports / "daily" / "2026-08-13.json").exists()
    notify_stage = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if json.loads(line).get("stage") == "notify"
    ]
    assert notify_stage[-1]["status"] == "skipped"
    assert "telegram not configured" in notify_stage[-1]["reason"]


def test_daily_brief_rejects_invalid_args(monkeypatch, tmp_path):
    recorder = RecordingTelegramSender(tmp_path / "reports")

    result, _, error = run_daily(
        monkeypatch, tmp_path, recorder, "--market-date", "2026-08-15", "--lookback", "0"
    )
    assert result == 1
    assert "--lookback" in error.getvalue()

    result, _, error = run_daily(
        monkeypatch, tmp_path, recorder, "--market-date", "2026-08-15", "--min-samples", "0"
    )
    assert result == 1
    assert "--min-samples" in error.getvalue()

    result, _, error = run_daily(
        monkeypatch, tmp_path, recorder, "--market-date", "2026-09-03"
    )
    assert result == 1
    assert "future" in error.getvalue()


def test_daily_brief_executive_is_compact_and_top_ranked(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    reports = tmp_path / "reports"
    symbols = ["ASII", "BBCA", "TLKM", "UNVR", "ICBP", "INCO"]
    seed_universe(cache_dir, symbols, date(2026, 8, 1))
    for symbol in symbols:
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
    recorder = RecordingTelegramSender(reports)

    result, output, error = run_daily(
        monkeypatch,
        tmp_path,
        recorder,
        "--market-date",
        "2026-08-13",
        "--lookback",
        "1",
        "--min-samples",
        "3",
    )

    assert result == 0, error.getvalue()
    assert len(recorder.messages) == 1
    text = recorder.messages[0][0]
    # Compact executive: top 5 shown, remainder summarized, warnings bounded.
    assert text.count("\n") < 40
    assert "... and 1 more ranked candidates" in text
    top_five = [line for line in text.splitlines() if line and line[0].isdigit()]
    assert len(top_five) == 5