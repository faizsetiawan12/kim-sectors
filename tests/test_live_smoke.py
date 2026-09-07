"""Opt-in live Sectors contract validation (issue #8).

Verifies the live Sectors API v2 schema contract against real network data.
This test is strictly opt-in and marked with @pytest.mark.live. It never runs
during normal test suite execution to prevent accidental API credit exhaustion.

To run:
    RUN_LIVE_SECTORS=1 pytest -m live tests/test_live_smoke.py
"""

from __future__ import annotations

import json
import os
from io import StringIO

import pytest

from main import main


@pytest.mark.live
def test_live_sectors_contract_is_bounded():
    """Verify live Sectors API v2 schema contract with minimal credit use.

    Spends at most 2 credits: 1 daily bar request and 1 broker summary request.
    Validates authentication, response schema, and field types against live endpoints.
    """
    if os.getenv("RUN_LIVE_SECTORS") != "1":
        pytest.skip("Skipping live Sectors contract test: set RUN_LIVE_SECTORS=1 to opt in.")

    api_key = os.getenv("SECTORS_API_KEY")
    if not api_key or not api_key.strip():
        pytest.skip("Skipping live Sectors contract test: SECTORS_API_KEY is not configured.")

    stdout = StringIO()
    stderr = StringIO()

    # Bounded tracer: single symbol BBCA, 2-day window (spends exactly 2 credits)
    exit_code = main(
        ["ping-sectors", "--symbol", "BBCA", "--window-days", "2"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, f"Live ping-sectors failed: {stderr.getvalue()}"
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    stages = [line.get("stage") for line in lines]
    assert stages == ["auth", "fetch", "validate", "complete"]

    complete_record = lines[-1]
    assert complete_record["status"] == "ok"
    assert complete_record["credits_spent"] <= 2, "Live check exceeded 2 credit bound"
