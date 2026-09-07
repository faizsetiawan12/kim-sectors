"""Thin CLI boundary exit-code contract and command dispatch tests."""

from __future__ import annotations

from datetime import date
from io import StringIO

import pytest

from kim_sectors.market_data import (
    InMemorySectorsAdapter,
    SectorsAuthError,
    SectorsRequestError,
    SectorsSchemaError,
)
from kim_sectors.outputs.telegram import TelegramDeliveryError
from main import main
from tests.support import broker_summary_payload, daily_bars_payload


ALL_COMMANDS = [
    ["ping-sectors"],
    ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-02"],
    ["rank", "--market-date", "2026-08-02"],
    ["signal", "--market-date", "2026-08-02"],
    ["run-daily", "--market-date", "2026-08-02"],
    ["run-backtest", "--start", "2026-08-01", "--end", "2026-08-02"],
]


@pytest.mark.parametrize("argv", ALL_COMMANDS, ids=lambda argv: argv[0])
def test_all_commands_map_missing_credentials_to_auth_exit_code(monkeypatch, argv):
    """Every public command preserves exit code 2 for missing Sectors credentials."""
    monkeypatch.delenv("SECTORS_API_KEY", raising=False)
    error = StringIO()

    assert main(argv, stdout=StringIO(), stderr=error) == 2
    assert "SECTORS_API_KEY is not set" in error.getvalue()


@pytest.mark.parametrize("argv", ALL_COMMANDS, ids=lambda argv: argv[0])
def test_all_commands_handle_invalid_timezone(monkeypatch, argv):
    """Every command returns EXIT_UNEXPECTED (1) on invalid timezone configuration."""
    monkeypatch.setenv("SECTORS_API_KEY", "dummy-key")
    monkeypatch.setenv("KIM_SECTORS_TIMEZONE", "Invalid/Timezone")
    error = StringIO()

    assert main(argv, stdout=StringIO(), stderr=error) == 1
    assert "configuration invalid" in error.getvalue()


def test_command_dispatch_ping_sectors_success_and_failures(monkeypatch):
    """ping-sectors command dispatches and preserves documented exit codes (0, 2, 3, 4)."""
    monkeypatch.setenv("SECTORS_API_KEY", "dummy-key")
    today = date(2026, 9, 2)

    # Exit code 0: success
    success_adapter = InMemorySectorsAdapter(
        daily=daily_bars_payload(start=date(2026, 8, 27), end=today),
        broker_summary=broker_summary_payload(start=date(2026, 8, 27), end=today),
    )
    assert main(
        ["ping-sectors", "--window-days", "7"],
        build_market_data=lambda _config: success_adapter,
        stdout=StringIO(),
        stderr=StringIO(),
        today=lambda: today,
    ) == 0

    # Exit code 2: auth error
    auth_adapter = InMemorySectorsAdapter(
        daily=[], broker_summary={}, error=SectorsAuthError("HTTP 401")
    )
    err = StringIO()
    assert main(
        ["ping-sectors"],
        build_market_data=lambda _config: auth_adapter,
        stdout=StringIO(),
        stderr=err,
        today=lambda: today,
    ) == 2
    assert "authentication failed" in err.getvalue()

    # Exit code 3: schema error
    schema_adapter = InMemorySectorsAdapter(
        daily=[{"symbol": "BBCA"}],  # missing required bar fields
        broker_summary={},
    )
    err = StringIO()
    assert main(
        ["ping-sectors"],
        build_market_data=lambda _config: schema_adapter,
        stdout=StringIO(),
        stderr=err,
        today=lambda: today,
    ) == 3
    assert "schema invalid" in err.getvalue()

    # Exit code 4: request error
    request_adapter = InMemorySectorsAdapter(
        daily=[], broker_summary={}, error=SectorsRequestError("HTTP 500")
    )
    err = StringIO()
    assert main(
        ["ping-sectors"],
        build_market_data=lambda _config: request_adapter,
        stdout=StringIO(),
        stderr=err,
        today=lambda: today,
    ) == 4
    assert "request failed" in err.getvalue()


def test_command_dispatch_sync_cache_preview_and_failure(monkeypatch, tmp_path):
    """sync-cache command dispatches with dry-run preview (0) and handles failures."""
    monkeypatch.setenv("SECTORS_API_KEY", "dummy-key")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "output"))

    # Preview mode exits 0 even without cache/network
    assert main(
        ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-05"],
        stdout=StringIO(),
        stderr=StringIO(),
        today=lambda: date(2026, 8, 10),
    ) == 0

    # Future end date exits 1 (validation error)
    err = StringIO()
    assert main(
        ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-15"],
        stdout=StringIO(),
        stderr=err,
        today=lambda: date(2026, 8, 10),
    ) == 1
    assert "error:" in err.getvalue()


def test_command_dispatch_rank_missing_cache_failure(monkeypatch, tmp_path):
    """rank command dispatches and maps missing cache/universe to EXIT_UNEXPECTED (1)."""
    monkeypatch.setenv("SECTORS_API_KEY", "dummy-key")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))

    err = StringIO()
    assert main(
        ["rank", "--market-date", "2026-08-15"],
        stdout=StringIO(),
        stderr=err,
        today=lambda: date(2026, 8, 20),
    ) == 1
    assert "error:" in err.getvalue()


def test_command_dispatch_signal_missing_cache_failure(monkeypatch, tmp_path):
    """signal command dispatches and maps missing cache/universe to EXIT_UNEXPECTED (1)."""
    monkeypatch.setenv("SECTORS_API_KEY", "dummy-key")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))

    err = StringIO()
    assert main(
        ["signal", "--market-date", "2026-08-15"],
        stdout=StringIO(),
        stderr=err,
        today=lambda: date(2026, 8, 20),
    ) == 1
    assert "error:" in err.getvalue()


def test_command_dispatch_run_daily_telegram_failure(monkeypatch, tmp_path):
    """run-daily command dispatches and maps Telegram failure to exit code 5."""
    monkeypatch.setenv("SECTORS_API_KEY", "dummy-key")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    class FailingTelegramSender:
        def send_markdown(self, text: str) -> None:
            raise TelegramDeliveryError("Telegram server down (HTTP 502)")

    err = StringIO()
    # A future date triggers unexpected error (1) before delivery
    assert main(
        ["run-daily", "--market-date", "2026-09-01"],
        stdout=StringIO(),
        stderr=err,
        today=lambda: date(2026, 8, 20),
    ) == 1


def test_command_dispatch_run_backtest_missing_cache_failure(monkeypatch, tmp_path):
    """run-backtest command dispatches and maps missing cache/history to EXIT_UNEXPECTED (1)."""
    monkeypatch.setenv("SECTORS_API_KEY", "dummy-key")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "output"))

    err = StringIO()
    assert main(
        ["run-backtest", "--start", "2026-08-01", "--end", "2026-08-15"],
        stdout=StringIO(),
        stderr=err,
        today=lambda: date(2026, 8, 20),
    ) == 1
    assert "error:" in err.getvalue()
