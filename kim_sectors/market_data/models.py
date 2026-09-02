"""Validated models for Sectors market data and cache synchronization."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DailyBar(StrictModel):
    symbol: str
    date: date
    close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    volume: int
    market_cap: Decimal


class BrokerSummaryRow(StrictModel):
    broker_code: str
    bfreq: int
    blot: int
    bval: Decimal
    bavg_per_share: Decimal | None
    sfreq: int
    slot: int
    sval: Decimal
    savg_per_share: Decimal | None
    nlot: int
    nval: Decimal
    navg_per_share: Decimal | None


class BrokerSummaryDay(StrictModel):
    date: date
    summary: list[BrokerSummaryRow]


class BrokerSummary(StrictModel):
    symbol: str
    start: date
    end: date
    data: list[BrokerSummaryDay]


class PingReport(StrictModel):
    symbol: str
    window_start: date
    window_end: date
    daily_bars: list[DailyBar]
    broker_summary: BrokerSummary
    credits_spent: int = Field(ge=0)
    completed_at: datetime


class UniverseResolution(StrictModel):
    """Normalized universe symbols plus the number of screener pages fetched."""

    index: str
    symbols: list[str]
    pages: int = Field(ge=1)
    source: str


class UniverseMembership(StrictModel):
    index: str
    symbols: list[str]
    pages: int = Field(default=1, ge=1)
    effective_date: date
    resolved_at: datetime
    source: str
    schema_version: str


class Provenance(StrictModel):
    source: str
    retrieved_at: datetime
    schema_version: str


class CachedDailyBar(StrictModel):
    symbol: str
    date: date
    close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    volume: int
    market_cap: Decimal
    provenance: Provenance


class CachedBrokerSummaryDay(StrictModel):
    symbol: str
    date: date
    summary: list[BrokerSummaryRow]
    provenance: Provenance


class DateSpan(StrictModel):
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class SyncChunk(StrictModel):
    symbol: str
    data_type: str
    start: date
    end: date
    estimated_credits: int = Field(ge=1)


class SyncPlan(StrictModel):
    index: str
    symbols: list[str]
    chunks: list[SyncChunk]
    estimated_credits: int = Field(ge=0)
    market_credits_unknown: bool = False
    universe_resolved: bool


class SyncReport(StrictModel):
    mode: str
    index: str
    symbols: list[str]
    chunks_planned: int = Field(ge=0)
    credits_spent: int = Field(ge=0)
    status: str
