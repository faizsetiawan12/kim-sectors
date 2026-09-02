from __future__ import annotations

from datetime import date

import pytest
import requests

from kim_sectors.config import SectorsConfig
from kim_sectors.market_data import (
    SectorsAuthError,
    SectorsHttpAdapter,
    SectorsRequestError,
    SectorsSchemaError,
    build_authorization_headers,
)

from .support import daily_bars_payload


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def config() -> SectorsConfig:
    return SectorsConfig(
        sectors_api_key="test-dummy-key-123",
        sectors_base_url="https://example.test/v2/",
    )


def test_authorization_header_has_no_bearer_prefix():
    assert build_authorization_headers("test-dummy-key-123") == {
        "Authorization": "test-dummy-key-123"
    }


def test_live_adapter_fetches_and_validates_daily_response():
    start = end = date(2026, 8, 26)
    session = FakeSession(
        FakeResponse(200, daily_bars_payload(start=start, end=end))
    )
    adapter = SectorsHttpAdapter(config(), session=session)

    bars = adapter.fetch_daily_bars("BBCA", start, end)

    assert len(bars) == 1
    args, kwargs = session.calls[0]
    assert args == ("https://example.test/v2/daily/BBCA/",)
    assert kwargs["headers"] == {"Authorization": "test-dummy-key-123"}
    assert kwargs["timeout"] == 30


@pytest.mark.parametrize("status_code", [401, 403])
def test_live_adapter_maps_auth_status(status_code):
    adapter = SectorsHttpAdapter(config(), session=FakeSession(FakeResponse(status_code)))

    with pytest.raises(SectorsAuthError, match="API key"):
        adapter.fetch_daily_bars("BBCA", date(2026, 8, 26), date(2026, 8, 26))


@pytest.mark.parametrize("status_code", [400, 429, 500])
def test_live_adapter_maps_request_status(status_code):
    adapter = SectorsHttpAdapter(config(), session=FakeSession(FakeResponse(status_code)))

    with pytest.raises(SectorsRequestError):
        adapter.fetch_daily_bars("BBCA", date(2026, 8, 26), date(2026, 8, 26))


def test_live_adapter_maps_transport_failure():
    class FailedSession(FakeSession):
        def get(self, *args, **kwargs):
            raise requests.Timeout("timed out")

    adapter = SectorsHttpAdapter(config(), session=FailedSession(None))

    with pytest.raises(SectorsRequestError, match="request failed"):
        adapter.fetch_daily_bars("BBCA", date(2026, 8, 26), date(2026, 8, 26))


def test_live_adapter_maps_non_json_body_to_schema_error():
    adapter = SectorsHttpAdapter(
        config(), session=FakeSession(FakeResponse(200, ValueError("not json")))
    )

    with pytest.raises(SectorsSchemaError, match="non-JSON"):
        adapter.fetch_daily_bars("BBCA", date(2026, 8, 26), date(2026, 8, 26))
