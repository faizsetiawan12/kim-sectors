"""Live HTTP adapter for Sectors API v2."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping

import requests
from pydantic import ValidationError

from ..config import SectorsConfig
from .errors import SectorsAuthError, SectorsRequestError, SectorsSchemaError
from .models import BrokerSummary, DailyBar, UniverseResolution
from .validate import parse_broker_summary, parse_daily_bars

DEFAULT_TIMEOUT_SECONDS = 30

UNIVERSE_INDEX_QUERY = "indices in ['{index}']"
UNIVERSE_PAGE_LIMIT = 30
UNIVERSE_ENDPOINT = "companies/"
UNIVERSE_SOURCE = "sectors"
MAX_UNIVERSE_PAGES = 1000

_SYMBOL_PATTERN = re.compile(r"^[A-Z]{4}(?:\.JK)?$", re.IGNORECASE)


def build_authorization_headers(api_key: str) -> dict[str, str]:
    """Build Sectors' raw API-key header (not a Bearer token)."""
    return {"Authorization": api_key}


def normalize_symbol(value: Any) -> str:
    """Validate and normalize an IDX symbol to bare uppercase form."""
    if not isinstance(value, str):
        raise ValueError("symbol must be a string")
    symbol = value.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("symbol must contain four letters, optionally followed by .JK")
    return symbol.removesuffix(".JK")


def parse_universe_page(payload: Any, *, endpoint: str) -> tuple[list[str], dict[str, Any]]:
    """Validate one companies-screener page, returning symbols and pagination."""
    try:
        if not isinstance(payload, dict):
            raise TypeError("response must be an object")
        results = payload.get("results")
        pagination = payload.get("pagination")
        if not isinstance(results, list) or not isinstance(pagination, dict):
            raise TypeError("response requires results and pagination")
        if not isinstance(pagination.get("has_next"), bool):
            raise TypeError("pagination.has_next must be boolean")
        if not isinstance(pagination.get("next_offset"), (int, type(None))):
            raise TypeError("pagination.next_offset must be integer or null")
        symbols = []
        for row in results:
            if not isinstance(row, dict):
                raise TypeError("universe rows must be objects")
            symbols.append(normalize_symbol(row.get("symbol")))
        return symbols, pagination
    except (TypeError, ValueError, ValidationError) as error:
        raise SectorsSchemaError(
            f"Unexpected universe response from {endpoint}: {error}"
        ) from error


class SectorsHttpAdapter:
    """Fetch and validate Sectors responses without exposing credentials."""

    def __init__(self, config: SectorsConfig, *, session: requests.Session | None = None):
        self._base_url = config.sectors_base_url.rstrip("/") + "/"
        self._headers = build_authorization_headers(config.api_key)
        self._session = session or requests.Session()

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        endpoint = f"daily/{symbol}/"
        payload = self._get(endpoint, params={"start": start.isoformat(), "end": end.isoformat()})
        return parse_daily_bars(payload, endpoint=f"/v2/{endpoint}")

    def fetch_broker_summary(
        self, symbol: str, start: date, end: date
    ) -> BrokerSummary:
        endpoint = f"broker-summary/{symbol}/"
        payload = self._get(endpoint, params={"start": start.isoformat(), "end": end.isoformat()})
        return parse_broker_summary(payload, endpoint=f"/v2/{endpoint}")

    def fetch_universe(self, index: str) -> UniverseResolution:
        symbols: list[str] = []
        offset = 0
        pages = 0
        while True:
            pages += 1
            if pages > MAX_UNIVERSE_PAGES:
                raise SectorsSchemaError(
                    "Unexpected universe response: pagination did not terminate"
                )
            endpoint = UNIVERSE_ENDPOINT
            params = {
                "where": UNIVERSE_INDEX_QUERY.format(index=index),
                "limit": UNIVERSE_PAGE_LIMIT,
                "offset": offset,
            }
            page_symbols, pagination = parse_universe_page(
                self._get(endpoint, params=params), endpoint=f"/v2/{endpoint}"
            )
            symbols.extend(page_symbols)
            if not pagination.get("has_next"):
                break
            next_offset = pagination.get("next_offset")
            if not isinstance(next_offset, int) or next_offset <= offset:
                raise SectorsSchemaError(
                    "Unexpected universe response: pagination did not advance"
                )
            offset = next_offset
        return UniverseResolution(
            index=index,
            symbols=_dedupe(symbols),
            pages=pages,
            source=UNIVERSE_SOURCE,
        )

    def _get(self, endpoint: str, *, params: Mapping[str, Any]) -> Any:
        url = self._base_url + endpoint
        try:
            response = self._session.get(
                url,
                headers=self._headers,
                params=params,
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


def _dedupe(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result
