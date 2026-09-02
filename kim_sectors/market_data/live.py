"""Live HTTP adapter for Sectors API v2."""

from __future__ import annotations

from datetime import date
from typing import Any

import requests

from ..config import SectorsConfig
from .errors import SectorsAuthError, SectorsRequestError, SectorsSchemaError
from .models import BrokerSummary, DailyBar
from .validate import parse_broker_summary, parse_daily_bars

DEFAULT_TIMEOUT_SECONDS = 30


def build_authorization_headers(api_key: str) -> dict[str, str]:
    """Build Sectors' raw API-key header (not a Bearer token)."""
    return {"Authorization": api_key}


class SectorsHttpAdapter:
    """Fetch and validate Sectors responses without exposing credentials."""

    def __init__(self, config: SectorsConfig, *, session: requests.Session | None = None):
        self._base_url = config.sectors_base_url.rstrip("/") + "/"
        self._headers = build_authorization_headers(config.api_key)
        self._session = session or requests.Session()

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        endpoint = f"daily/{symbol}/"
        payload = self._get(endpoint, start=start, end=end)
        return parse_daily_bars(payload, endpoint=f"/v2/{endpoint}")

    def fetch_broker_summary(
        self, symbol: str, start: date, end: date
    ) -> BrokerSummary:
        endpoint = f"broker-summary/{symbol}/"
        payload = self._get(endpoint, start=start, end=end)
        return parse_broker_summary(payload, endpoint=f"/v2/{endpoint}")

    def _get(self, endpoint: str, *, start: date, end: date) -> Any:
        url = self._base_url + endpoint
        try:
            response = self._session.get(
                url,
                headers=self._headers,
                params={"start": start.isoformat(), "end": end.isoformat()},
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise SectorsRequestError(f"Sectors request failed: {error}") from error

        if response.status_code in (401, 403):
            raise SectorsAuthError(
                f"Sectors rejected the API key (HTTP {response.status_code})"
            )
        if response.status_code == 429:
            raise SectorsRequestError("Sectors rate limit exceeded (HTTP 429)")
        if not 200 <= response.status_code < 300:
            raise SectorsRequestError(
                f"Sectors request failed (HTTP {response.status_code})"
            )
        try:
            return response.json()
        except ValueError as error:
            raise SectorsSchemaError("Sectors returned a non-JSON response") from error
