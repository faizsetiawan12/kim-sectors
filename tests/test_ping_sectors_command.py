from __future__ import annotations

import json
from datetime import date
from io import StringIO

from main import main
from kim_sectors.market_data import (
    InMemorySectorsAdapter,
    SectorsAuthError,
    SectorsSchemaError,
)

from .support import broker_summary_payload, daily_bars_payload, malformed_daily_bars_payload


def make_adapter(start: date, end: date) -> InMemorySectorsAdapter:
    return InMemorySectorsAdapter(
        daily=daily_bars_payload(start=start, end=end),
        broker_summary=broker_summary_payload(start=start, end=end),
    )


def test_ping_sectors_reports_each_stage_for_controlled_response(monkeypatch):
    start = date(2026, 8, 27)
    end = date(2026, 9, 2)
    adapter = make_adapter(start, end)
    out = StringIO()
    err = StringIO()

    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    exit_code = main(
        ["ping-sectors", "--window-days", "7"],
        build_market_data=lambda _config: adapter,
        stdout=out,
        stderr=err,
        today=lambda: end,
    )

    assert exit_code == 0
    assert err.getvalue() == ""
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [line["stage"] for line in lines] == [
        "auth",
        "fetch",
        "validate",
        "complete",
    ]
    assert all(line["status"] == "ok" for line in lines)
    assert lines[-1]["credits_spent"] == 2
    assert "test-dummy-key-123" not in out.getvalue()


def test_ping_sectors_reports_auth_failure_without_traceback(monkeypatch):
    adapter = InMemorySectorsAdapter(
        daily=[],
        broker_summary={},
        error=SectorsAuthError("Sectors rejected the API key (HTTP 401)"),
    )
    out = StringIO()
    err = StringIO()
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")

    exit_code = main(
        ["ping-sectors"],
        build_market_data=lambda _config: adapter,
        stdout=out,
        stderr=err,
        today=lambda: date(2026, 9, 2),
    )

    assert exit_code == 2
    assert "error: authentication failed:" in err.getvalue()
    assert "Traceback" not in err.getvalue()
    assert "test-dummy-key-123" not in out.getvalue() + err.getvalue()


def test_ping_sectors_reports_malformed_response(monkeypatch):
    adapter = InMemorySectorsAdapter(
        daily=malformed_daily_bars_payload(),
        broker_summary={},
    )
    out = StringIO()
    err = StringIO()
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")

    exit_code = main(
        ["ping-sectors"],
        build_market_data=lambda _config: adapter,
        stdout=out,
        stderr=err,
        today=lambda: date(2026, 9, 2),
    )

    assert exit_code == 3
    assert "response schema invalid" in err.getvalue()
    assert "close" in err.getvalue()
    assert "test-dummy-key-123" not in out.getvalue() + err.getvalue()


def test_ping_sectors_logs_failed_auth_stage(monkeypatch):
    adapter = InMemorySectorsAdapter(
        daily=[],
        broker_summary={},
        error=SectorsAuthError("Sectors rejected the API key (HTTP 401)"),
    )
    out = StringIO()
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")

    assert main(
        ["ping-sectors"],
        build_market_data=lambda _config: adapter,
        stdout=out,
        stderr=StringIO(),
        today=lambda: date(2026, 9, 2),
    ) == 2
    stages = [json.loads(line) for line in out.getvalue().splitlines()]
    assert stages[-1] == {
        "event": "sector_ping_stage",
        "stage": "auth",
        "status": "error",
        "ts": stages[-1]["ts"],
    }


def test_ping_sectors_handles_invalid_timezone(monkeypatch):
    monkeypatch.setenv("SECTORS_API_KEY", "test-dummy-key-123")
    monkeypatch.setenv("KIM_SECTORS_TIMEZONE", "not-a-timezone")
    err = StringIO()

    assert main(["ping-sectors"], stdout=StringIO(), stderr=err) == 1
    assert "configuration invalid" in err.getvalue()
    assert "Traceback" not in err.getvalue()


def test_ping_sectors_requires_api_key(monkeypatch):
    monkeypatch.delenv("SECTORS_API_KEY", raising=False)
    out = StringIO()
    err = StringIO()
    called = False

    def factory(_config):
        nonlocal called
        called = True
        raise AssertionError("factory should not be called without an API key")

    exit_code = main(["ping-sectors"], build_market_data=factory, stdout=out, stderr=err)

    assert exit_code == 2
    assert "SECTORS_API_KEY is not set" in err.getvalue()
    assert called is False
    assert out.getvalue() == ""
