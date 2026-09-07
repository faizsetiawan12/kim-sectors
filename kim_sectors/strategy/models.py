"""Strategy models for momentum ranking."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RankedCandidate(StrictModel):
    symbol: str
    market_date: date
    momentum: float
    start_date: date
    end_date: date
    start_close: str
    end_close: str
    lookback: int = Field(ge=1)


class IneligibleCandidate(StrictModel):
    symbol: str
    market_date: date
    reason: str
    lookback: int = Field(ge=1)


class RankReport(StrictModel):
    mode: str
    index: str
    market_date: date
    lookback: int = Field(ge=1)
    candidates: list[RankedCandidate]
    ineligible: list[IneligibleCandidate]
    status: str
