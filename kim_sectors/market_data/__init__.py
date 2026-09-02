"""Public market-data seam and adapters."""

from .base import SectorsMarketData
from .errors import (
    MarketDataError,
    SectorsAuthError,
    SectorsRequestError,
    SectorsSchemaError,
)
from .live import SectorsHttpAdapter, build_authorization_headers
from .memory import InMemorySectorsAdapter
from .models import BrokerSummary, DailyBar, PingReport
from .ping import DEFAULT_PING_SYMBOL, ping_sectors

__all__ = [
    "BrokerSummary",
    "DailyBar",
    "DEFAULT_PING_SYMBOL",
    "InMemorySectorsAdapter",
    "MarketDataError",
    "PingReport",
    "SectorsAuthError",
    "SectorsHttpAdapter",
    "SectorsMarketData",
    "SectorsRequestError",
    "SectorsSchemaError",
    "build_authorization_headers",
    "ping_sectors",
]
