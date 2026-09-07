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
    # Raw cache strings (Decimal dumps as string in JSON) to preserve audit values.
    start_close: str
    end_close: str
    lookback: int = Field(ge=1)


class IneligibleCandidate(StrictModel):
    symbol: str
    market_date: date
    reason: str
    lookback: int = Field(ge=1)


class RankReport(StrictModel):
    # mode/status mirror SyncReport for a consistent workflow contract.
    mode: str
    index: str
    market_date: date
    lookback: int = Field(ge=1)
    candidates: list[RankedCandidate]
    ineligible: list[IneligibleCandidate]
    status: str


class SignalCandidate(StrictModel):
    symbol: str
    market_date: date
    momentum: float
    samples: int = Field(ge=0)
    win_prob: float
    avg_gain: float
    avg_loss: float
    reward_risk: float
    broker_ev: float
    signal_score: float
    start_date: date
    end_date: date
    start_close: str
    end_close: str
    lookback: int = Field(ge=1)


class SignalHighlight(StrictModel):
    symbol: str
    signal_score: float
    momentum: float
    broker_ev: float
    note: str


class SignalReport(StrictModel):
    mode: str
    index: str
    market_date: date
    lookback: int = Field(ge=1)
    min_samples: int = Field(ge=1)
    candidates: list[SignalCandidate]
    ineligible: list[IneligibleCandidate]
    highlight: SignalHighlight | None = None
    status: str
