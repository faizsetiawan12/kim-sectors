"""Thin CLI boundary exit-code contract tests."""

from __future__ import annotations

from io import StringIO

import pytest

from main import main


COMMANDS = [
    ["ping-sectors"],
    ["sync-cache", "--start", "2026-08-01", "--end", "2026-08-02"],
    ["rank", "--market-date", "2026-08-02"],
    ["signal", "--market-date", "2026-08-02"],
    ["run-daily", "--market-date", "2026-08-02"],
    ["run-backtest", "--start", "2026-08-01", "--end", "2026-08-02"],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda argv: argv[0])
def test_all_commands_map_missing_credentials_to_auth_exit_code(monkeypatch, argv):
    """Every public command preserves exit code 2 for missing Sectors credentials."""
    monkeypatch.delenv("SECTORS_API_KEY", raising=False)
    error = StringIO()

    assert main(argv, stdout=StringIO(), stderr=error) == 2
    assert "SECTORS_API_KEY is not set" in error.getvalue()
