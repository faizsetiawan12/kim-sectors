"""Operational tests for KIM Sectors (issue #8).

Verifies:
1. Absence of brokerage authentication, order execution, and trading APIs.
2. Complete reproducible demo workflow path.
3. Structured logging distinguishes fetch, validation, scoring, backtesting,
   reporting, and notification stages without leaking secrets.
4. Post-market cron schedule compatibility for Asia/Jakarta.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from datetime import date
from io import StringIO
from pathlib import Path


import kim_sectors
from main import main
from tests.test_daily_brief_command import broker_payload_for_span, mixed_daily_payload
from kim_sectors.market_data.memory import InMemorySectorsAdapter

REPOSITORY_ROOT = Path(__file__).parents[1]


def test_cron_launcher_and_readme_document_wib_schedule():
    launcher = REPOSITORY_ROOT / "scripts" / "run_daily_cron.sh"
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert launcher.exists()
    assert launcher.stat().st_mode & 0o111
    assert "CRON_TZ=Asia/Jakarta" in readme
    assert "run_daily_cron.sh" in readme
    assert "16:15" in readme


def test_readme_documents_reproducible_competition_workflow():
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8").lower()
    required_terms = (
        "problem",
        "sectors api",
        "lq45",
        "momentum",
        "broker ev",
        "data cache",
        "backtest run",
        "human",
        "600",
        "limitation",
        "telegram",
        "research and decision support only",
    )
    for term in required_terms:
        assert term in readme


def test_daily_logs_required_operational_stages(monkeypatch, tmp_path):
    """Controlled run emits the stages an operator needs to audit."""
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "reports"))
    adapter = InMemorySectorsAdapter(
        universe=["BBCA"],
        daily=mixed_daily_payload,
        broker_summary=broker_payload_for_span,
    )
    output = StringIO()

    assert main(
        ["run-daily"],
        build_market_data=lambda _config: adapter,
        stdout=output,
        stderr=StringIO(),
        today=lambda: date(2026, 9, 2),
    ) == 0

    stages = {json.loads(line)["stage"] for line in output.getvalue().splitlines()}
    assert {"fetch", "validate", "scoring", "report", "notify"}.issubset(stages)
    assert all("test-dummy-key-123" not in line for line in output.getvalue().splitlines())


def test_backtest_logs_backtesting_stage(monkeypatch, tmp_path):
    """A controlled cached replay identifies its backtesting stage."""
    # The complete demo-stage test above covers live fetch and reporting. This
    # assertion checks the backtest stage through the existing command seam.
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KIM_SECTORS_OUTPUT_DIR", str(tmp_path / "reports"))
    output = StringIO()
    error = StringIO()

    # Seed the smallest valid replay so the backtest stage is observable.
    from tests.test_backtest_command import seed_universe, seed_win_loss_history

    cache_dir = tmp_path / "cache"
    seed_universe(cache_dir, ["BBCA"], date(2026, 8, 1))
    seed_win_loss_history(cache_dir, "BBCA")
    result = main(
        ["run-backtest", "--start", "2026-08-10", "--end", "2026-08-12", "--lookback", "1", "--min-samples", "1"],
        stdout=output,
        stderr=error,
        today=lambda: date(2026, 9, 2),
    )

    assert result == 0, error.getvalue()
    assert {"backtesting", "scoring"}.issubset(
        json.loads(line)["stage"] for line in output.getvalue().splitlines()
    )


def test_live_checks_are_explicitly_marked():
    """Live API checks have a dedicated marker and are not normal tests."""
    marker_lines = (REPOSITORY_ROOT / "tests" / "test_live_smoke.py").read_text(
        encoding="utf-8"
    )
    assert "pytest.mark.live" in marker_lines
    assert "RUN_LIVE_SECTORS" in marker_lines


def test_telegram_checks_are_explicitly_marked():
    """Telegram checks require a separate opt-in marker and flag."""
    marker_lines = (REPOSITORY_ROOT / "tests" / "test_telegram_smoke.py").read_text(
        encoding="utf-8"
    )
    assert "pytest.mark.telegram" in marker_lines
    assert "RUN_TELEGRAM_SMOKE" in marker_lines


def test_no_brokerage_or_order_execution_capability():
    """Verify the repository contains no brokerage or live order capabilities.

    Acceptance criterion: Documentation and operational tests verify no
    brokerage/order-execution capability is present.
    """
    forbidden_terms = [
        "stockbit",
        "ajaib",
        "mandiri_sekuritas",
        "indopremier",
        "ipat",
        "ccxt",
        "alpaca",
        "place_order",
        "submit_order",
        "cancel_order",
        "execute_trade",
        "live_trading",
        "broker_auth",
        "carina",
    ]

    # Walk all modules in kim_sectors package.
    package = kim_sectors
    for _, module_name, _ in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        mod = importlib.import_module(module_name)
        file_path = getattr(mod, "__file__", "")
        if not file_path or not file_path.endswith(".py"):
            continue
        content = Path(file_path).read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            assert term not in content, (
                f"Forbidden trading/brokerage execution term '{term}' found in {module_name}"
            )
