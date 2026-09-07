"""Workflow seam: orchestrate the post-market daily pipeline end to end."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from logging import Logger
from pathlib import Path
from zoneinfo import ZoneInfo

from ..market_data.base import SectorsMarketData, SyncMarketData
from ..market_data.cache import read_cache
from ..market_data.errors import CacheError
from ..market_data.sync import sync_cache
from ..observability import log_stage
from ..outputs.brief import (
    DISCLAIMER,
    EXECUTIVE_TOP_K,
    BriefFreshness,
    BriefUniverse,
    DailyBrief,
    render_executive,
    save_brief,
)
from ..outputs.telegram import TelegramDeliveryError, TelegramSender
from ..strategy.cache_access import select_membership
from ..strategy.models import StrictModel
from ..strategy.signal import rank_signal

SYNC_SPAN_DAYS = 60


class DailyRunReport(StrictModel):
    mode: str = "daily"
    index: str
    market_date: date
    status: str = "ok"
    artifact_paths: list[str]
    notify_status: str  # "sent" | "skipped"


def _add_days(value: date, days: int) -> date:
    return value + timedelta(days=days)


def _latest_retrieved_at(cache_dir: Path, symbols: list[str]) -> datetime | None:
    """Latest cache retrieval timestamp across the universe's cached rows."""
    latest: datetime | None = None
    for symbol in symbols:
        for data_type in ("daily", "broker"):
            try:
                rows, _ = read_cache(symbol, data_type, cache_dir)
            except CacheError:
                continue
            for row in rows:
                provenance = row.get("provenance") or {}
                try:
                    retrieved = datetime.fromisoformat(str(provenance.get("retrieved_at")))
                except (TypeError, ValueError):
                    continue
                if latest is None or retrieved > latest:
                    latest = retrieved
    return latest


def run_daily(
    *,
    client: SectorsMarketData | SyncMarketData,
    index: str,
    market_date: date,
    lookback: int,
    min_samples: int,
    cache_dir: Path,
    output_dir: Path,
    timezone: ZoneInfo,
    logger: Logger,
    today: date,
    sender: TelegramSender | None,
    fetch: bool,
) -> DailyRunReport:
    """Execute the post-market pipeline and return its report.

    Stages: fetch/validate (live only), factor calculation, ranking, brief
    artifacts, Telegram delivery. Artifacts are always written before any
    delivery attempt; a delivery failure propagates as TelegramDeliveryError
    after the artifacts already exist on disk.
    """
    if lookback < 1:
        raise ValueError("--lookback must be >= 1")
    if min_samples < 1:
        raise ValueError("--min-samples must be >= 1")
    if market_date > today:
        raise ValueError("--market-date cannot be in the future")

    if fetch:
        start = _add_days(market_date, -SYNC_SPAN_DAYS)
        sync_cache(
            client,
            index=index,
            start=start,
            end=market_date,
            cache_dir=cache_dir,
            timezone=timezone,
            logger=logger,
            today=today,
            fetch=True,
        )
    else:
        log_stage(logger, "sync", status="skipped", reason="manual replay uses cached data")

    membership = select_membership(index, market_date, cache_dir)
    signal = rank_signal(
        index=index,
        market_date=market_date,
        lookback=lookback,
        min_samples=min_samples,
        cache_dir=cache_dir,
        logger=logger,
        today=today,
    )
    if signal.status != "ok":
        raise RuntimeError(f"signal ranking failed with status {signal.status!r}")

    generated_at = datetime.now(timezone)
    freshness = BriefFreshness(
        market_date=market_date,
        retrieved_at=_latest_retrieved_at(cache_dir, membership.symbols),
    )
    universe = BriefUniverse(
        index=index,
        members=len(membership.symbols),
        eligible=len(signal.candidates),
        ineligible=len(signal.ineligible),
    )
    brief = DailyBrief(
        mode="daily",
        index=index,
        market_date=market_date,
        generated_at=generated_at,
        timezone=str(timezone),
        freshness=freshness,
        universe=universe,
        lookback=lookback,
        min_samples=min_samples,
        candidates=signal.candidates,
        ineligible=signal.ineligible,
        highlight=signal.highlight,
        disclaimer=DISCLAIMER,
    )
    paths = save_brief(brief, output_dir)
    log_stage(
        logger,
        "report",
        status="ok",
        artifacts=[str(path) for path in paths],
    )

    executive = render_executive(brief, top_k=EXECUTIVE_TOP_K)
    notify_status = _notify(sender, executive, logger)
    log_stage(
        logger,
        "complete",
        mode="daily",
        index=index,
        market_date=market_date.isoformat(),
        lookback=lookback,
        min_samples=min_samples,
        eligible=len(signal.candidates),
        ineligible=len(signal.ineligible),
        artifacts=[str(path) for path in paths],
        notify=notify_status,
        status="ok",
    )
    return DailyRunReport(
        index=index,
        market_date=market_date,
        status="ok",
        artifact_paths=[str(path) for path in paths],
        notify_status=notify_status,
    )


def _notify(sender: TelegramSender | None, executive: str, logger: Logger) -> str:
    if sender is None:
        log_stage(logger, "notify", status="skipped", reason="telegram not configured")
        return "skipped"
    try:
        sender.send(executive)
    except TelegramDeliveryError as error:
        log_stage(logger, "notify", status="error", error=str(error))
        raise
    log_stage(logger, "notify", status="ok", chars=len(executive))
    return "sent"