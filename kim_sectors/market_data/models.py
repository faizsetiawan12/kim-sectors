"""Validated models for the small Sectors tracer response."""

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
    volume: int
    market_cap: Decimal


class BrokerSummaryRow(StrictModel):
    broker_code: str
    bfreq: int
    blot: int
    bval: Decimal
    bavg_per_share: Decimal
    sfreq: int
    slot: int
    sval: Decimal
    savg_per_share: Decimal
    nlot: int
    nval: Decimal
    navg_per_share: Decimal


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
