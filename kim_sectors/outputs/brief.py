"""Daily market brief artifacts: Markdown, JSON, and Telegram executive text."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from pydantic import Field

from ..strategy.models import (
    IneligibleCandidate,
    SignalCandidate,
    SignalHighlight,
    StrictModel,
)

DISCLAIMER = "Research and decision support only; not a buy or sell recommendation."
EXECUTIVE_TOP_K = 5


class BriefFreshness(StrictModel):
    market_date: date
    retrieved_at: datetime | None = None


class BriefUniverse(StrictModel):
    index: str
    members: int = Field(ge=0)
    eligible: int = Field(ge=0)
    ineligible: int = Field(ge=0)


class DailyBrief(StrictModel):
    mode: str = "daily"
    index: str
    market_date: date
    generated_at: datetime
    timezone: str
    freshness: BriefFreshness
    universe: BriefUniverse
    lookback: int = Field(ge=1)
    min_samples: int = Field(ge=1)
    candidates: list[SignalCandidate]
    ineligible: list[IneligibleCandidate]
    highlight: SignalHighlight | None = None
    disclaimer: str


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _signed_percent(value: float) -> str:
    return f"{value * 100:+.1f}%"


def _score(value: float) -> str:
    return f"{value:+.4f}"


def _wib(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def render_markdown(brief: DailyBrief) -> str:
    lines = [
        f"# Daily Market Brief - {brief.index.upper()}",
        "",
        f"- **Market date**: {brief.market_date.isoformat()}",
        f"- **Generated at**: {_wib(brief.generated_at)} ({brief.timezone})",
    ]
    if brief.freshness.retrieved_at is not None:
        lines.append(
            f"- **Data freshness**: cached {_wib(brief.freshness.retrieved_at)} "
            f"through {brief.freshness.market_date.isoformat()}"
        )
    else:
        lines.append(
            f"- **Data freshness**: through {brief.freshness.market_date.isoformat()}"
        )
    universe = brief.universe
    lines.append(
        f"- **Universe coverage**: {universe.members} members, "
        f"{universe.eligible} ranked, {universe.ineligible} excluded"
    )
    lines.append("")
    if brief.candidates:
        lines.append("## Ranked candidates")
        lines.append("")
        lines.append(
            "| Rank | Symbol | Momentum | Win prob | Avg gain | Avg loss | "
            "R/R | Broker EV | Signal |"
        )
        lines.append(
            "|------|--------|----------|----------|----------|----------|-----|-----------|--------|"
        )
        for rank, candidate in enumerate(brief.candidates, start=1):
            lines.append(
                f"| {rank} | {candidate.symbol} | {_signed_percent(candidate.momentum)} | "
                f"{_percent(candidate.win_prob)} | {_signed_percent(candidate.avg_gain)} | "
                f"{_signed_percent(candidate.avg_loss)} | {candidate.reward_risk:.2f} | "
                f"{_score(candidate.broker_ev)} | {_score(candidate.signal_score)} |"
            )
        lines.append("")
    if brief.highlight is not None:
        highlight = brief.highlight
        lines.append("## Highlight")
        lines.append("")
        lines.append(
            f"- **{highlight.symbol}** - signal {_score(highlight.signal_score)} "
            f"(momentum {_signed_percent(highlight.momentum)} x "
            f"broker EV {_score(highlight.broker_ev)})"
        )
        lines.append("")
    if brief.ineligible:
        lines.append("## Exclusions and warnings")
        lines.append("")
        for item in brief.ineligible:
            lines.append(f"- {item.symbol}: {item.reason}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"> {brief.disclaimer}")
    return "\n".join(lines)


def render_json(brief: DailyBrief) -> str:
    return json.dumps(brief.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def render_executive(brief: DailyBrief, *, top_k: int = EXECUTIVE_TOP_K) -> str:
    """Render the compact Telegram brief from the same DailyBrief model."""
    lines = [
        f"KIM Daily Brief - {brief.index.upper()} - {brief.market_date.isoformat()}",
        f"Universe: {brief.universe.members} members | "
        f"ranked {brief.universe.eligible} | excluded {brief.universe.ineligible}",
    ]
    for rank, candidate in enumerate(brief.candidates[:top_k], start=1):
        lines.append(
            f"{rank}. {candidate.symbol} - signal {_score(candidate.signal_score)} "
            f"(momentum {_signed_percent(candidate.momentum)} | "
            f"EV {_score(candidate.broker_ev)} | win {_percent(candidate.win_prob)} | "
            f"R/R {candidate.reward_risk:.2f})"
        )
    if len(brief.candidates) > top_k:
        lines.append(f"... and {len(brief.candidates) - top_k} more ranked candidates")
    if brief.ineligible:
        lines.append(f"Warnings: {len(brief.ineligible)} excluded")
        for item in brief.ineligible[:top_k]:
            lines.append(f"- {item.symbol}: {item.reason}")
        if len(brief.ineligible) > top_k:
            lines.append(f"- ... and {len(brief.ineligible) - top_k} more")
    lines.append("")
    lines.append(brief.disclaimer)
    return "\n".join(lines)


def save_brief(brief: DailyBrief, output_dir: Path) -> list[Path]:
    """Write Markdown then JSON artifacts; returns [markdown, json] paths."""
    directory = output_dir / "daily"
    directory.mkdir(parents=True, exist_ok=True)
    markdown_path = directory / f"{brief.market_date.isoformat()}.md"
    json_path = directory / f"{brief.market_date.isoformat()}.json"
    markdown_path.write_text(render_markdown(brief))
    json_path.write_text(render_json(brief))
    return [markdown_path, json_path]