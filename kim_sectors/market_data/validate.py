"""Convert untrusted Sectors JSON into validated domain models."""

from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .errors import SectorsSchemaError
from .models import BrokerSummary, DailyBar

_DAILY_ADAPTER = TypeAdapter(list[DailyBar])


def _schema_error(endpoint: str, model_name: str, error: Exception) -> SectorsSchemaError:
    detail = str(error).replace("\n", " ")[:300]
    return SectorsSchemaError(
        f"Unexpected {model_name} response from {endpoint}: {detail}"
    )


def parse_daily_bars(payload: Any, *, endpoint: str = "/daily/") -> list[DailyBar]:
    """Validate a daily-bars JSON value, never silently repairing it."""
    try:
        return _DAILY_ADAPTER.validate_python(payload)
    except (ValidationError, TypeError, ValueError) as error:
        raise _schema_error(endpoint, "daily bars", error) from error


def parse_broker_summary(
    payload: Any, *, endpoint: str = "/broker-summary/"
) -> BrokerSummary:
    """Validate a broker-summary JSON value, never silently dropping rows."""
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        return BrokerSummary.model_validate(payload)
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _schema_error(endpoint, "broker summary", error) from error
