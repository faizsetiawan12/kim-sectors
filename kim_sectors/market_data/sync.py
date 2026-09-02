"""Credit-aware cache synchronization for universe resolution and market data."""

from __future__ import annotations

from datetime import date, datetime
from logging import Logger
from pathlib import Path
from zoneinfo import ZoneInfo

from ..observability import log_stage
from .base import SectorsMarketData, SyncMarketData
from .cache import load_universe_membership, read_cache, write_cache
from .errors import SectorsSchemaError
from .models import (
    CachedBrokerSummaryDay,
    CachedDailyBar,
    DateSpan,
    Provenance,
    SyncChunk,
    SyncPlan,
    SyncReport,
)
from .universe import resolve_universe

DAILY_MAX_DAYS = 90
BROKER_MAX_DAYS = 14
MARKET_CREDIT_PER_CHUNK = 1
UNIVERSE_CREDIT_PER_PAGE = 1
SCHEMA_VERSION = "1"


def _add_days(value: date, days: int) -> date:
    return date.fromordinal(value.toordinal() + days)


def _subtract_spans(requested: DateSpan, covered: list[DateSpan]) -> list[DateSpan]:
    """Return inclusive portions of *requested* not covered by *covered*."""
    missing: list[DateSpan] = []
    cursor = requested.start
    for span in sorted(covered, key=lambda item: item.start):
        if span.end < cursor:
            continue
        if span.start > requested.end:
            break
        if span.start > cursor:
            missing.append(DateSpan(start=cursor, end=_add_days(span.start, -1)))
        if span.end >= requested.end:
            return missing
        cursor = _add_days(max(cursor, span.end), 1)
    if cursor <= requested.end:
        missing.append(DateSpan(start=cursor, end=requested.end))
    return missing


def _chunk_span(span: DateSpan, max_days: int) -> list[DateSpan]:
    """Split an inclusive span into consecutive sub-spans of at most *max_days*."""
    chunks: list[DateSpan] = []
    cursor = span.start
    while cursor <= span.end:
        chunk_end = min(_add_days(cursor, max_days - 1), span.end)
        chunks.append(DateSpan(start=cursor, end=chunk_end))
        cursor = _add_days(chunk_end, 1)
    return chunks


def _plan_for_symbols(
    index: str,
    symbols: list[str],
    start: date,
    end: date,
    cache_dir: Path,
    logger: Logger,
) -> SyncPlan:
    if not symbols:
        raise SectorsSchemaError(f"Universe '{index}' resolved to an empty symbol list")
    chunks: list[SyncChunk] = []
    for symbol in symbols:
        for data_type, max_days in (
            ("daily", DAILY_MAX_DAYS),
            ("broker", BROKER_MAX_DAYS),
        ):
            _, covered = read_cache(symbol, data_type, cache_dir)
            for span in _subtract_spans(DateSpan(start=start, end=end), covered):
                for sub in _chunk_span(span, max_days):
                    chunks.append(
                        SyncChunk(
                            symbol=symbol,
                            data_type=data_type,
                            start=sub.start,
                            end=sub.end,
                            estimated_credits=MARKET_CREDIT_PER_CHUNK,
                        )
                    )
    total = sum(chunk.estimated_credits for chunk in chunks)
    log_stage(
        logger,
        "plan",
        status="ok",
        symbols=len(symbols),
        chunks=len(chunks),
        estimated_credits=total,
        market_credits_unknown=False,
    )
    return SyncPlan(
        index=index,
        symbols=symbols,
        chunks=chunks,
        estimated_credits=total,
        market_credits_unknown=False,
        universe_resolved=True,
    )


def _empty_plan(index: str, logger: Logger) -> SyncPlan:
    plan = SyncPlan(
        index=index,
        symbols=[],
        chunks=[],
        estimated_credits=UNIVERSE_CREDIT_PER_PAGE,
        market_credits_unknown=True,
        universe_resolved=False,
    )
    log_stage(
        logger,
        "plan",
        status="unresolved_universe",
        estimated_credits=plan.estimated_credits,
        market_credits_unknown=True,
    )
    return plan


def sync_cache(
    client: SectorsMarketData | SyncMarketData,
    *,
    index: str,
    start: date,
    end: date,
    cache_dir: Path,
    timezone: ZoneInfo,
    logger: Logger,
    today: date,
    fetch: bool = False,
    refresh_universe: bool = False,
) -> SyncReport:
    """Preview or execute a credit-aware synchronization of the configured universe."""
    if start > end:
        raise ValueError("--start must be on or before --end")
    if end > today:
        raise ValueError("--end cannot be in the future")

    membership = load_universe_membership(index, cache_dir)

    if membership is not None and not refresh_universe:
        log_stage(
            logger, "universe", status="reused", index=index, members=len(membership.symbols)
        )
    elif membership is not None and not fetch:
        log_stage(
            logger,
            "universe",
            status="reused",
            index=index,
            members=len(membership.symbols),
            refresh_pending=True,
        )
    else:
        log_stage(logger, "universe", status="unresolved", index=index)

    if fetch:
        if membership is None or refresh_universe:
            log_stage(
                logger,
                "plan",
                status="preflight",
                estimated_credits=UNIVERSE_CREDIT_PER_PAGE,
                market_credits_unknown=True,
            )
        if membership is None or refresh_universe:
            membership = resolve_universe(
                client,
                index=index,
                cache_dir=cache_dir,
                timezone=timezone,
                effective_date=today,
                logger=logger,
            )
            universe_credits = membership.pages
        else:
            universe_credits = 0
        plan = _plan_for_symbols(
            index, membership.symbols, start, end, cache_dir, logger
        )
        report = _execute_plan(client, plan, cache_dir, timezone, logger)
        total_credits = universe_credits + report.credits_spent
        log_stage(
            logger,
            "complete",
            mode="fetch",
            chunks_planned=len(plan.chunks),
            credits_spent=total_credits,
            status="ok",
        )
        return SyncReport(
            mode="fetch",
            index=report.index,
            symbols=report.symbols,
            chunks_planned=report.chunks_planned,
            credits_spent=total_credits,
            status="ok",
        )

    if membership is None:
        plan = _empty_plan(index, logger)
    else:
        plan = _plan_for_symbols(
            index, membership.symbols, start, end, cache_dir, logger
        )
    log_stage(
        logger,
        "complete",
        mode="preview",
        chunks_planned=len(plan.chunks),
        estimated_credits=plan.estimated_credits,
        status="ok",
    )
    return SyncReport(
        mode="preview",
        index=index,
        symbols=plan.symbols,
        chunks_planned=len(plan.chunks),
        credits_spent=0,
        status="ok",
    )


def _execute_plan(
    client: SectorsMarketData | SyncMarketData,
    plan: SyncPlan,
    cache_dir: Path,
    timezone: ZoneInfo,
    logger: Logger,
) -> SyncReport:
    credits_spent = 0
    for chunk in plan.chunks:
        provenance = Provenance(
            source="sectors",
            retrieved_at=datetime.now(timezone),
            schema_version=SCHEMA_VERSION,
        )
        if chunk.data_type == "daily":
            bars = client.fetch_daily_bars(chunk.symbol, chunk.start, chunk.end)
            rows: list[dict] = []
            seen: set[date] = set()
            for bar in bars:
                if bar.symbol.removesuffix(".JK").upper() != chunk.symbol.upper():
                    raise SectorsSchemaError(
                        f"Daily response symbol does not match requested symbol {chunk.symbol}"
                    )
                if not chunk.start <= bar.date <= chunk.end:
                    raise SectorsSchemaError(
                        f"Daily response for {chunk.symbol} has a row outside the requested range"
                    )
                if bar.date in seen:
                    raise SectorsSchemaError(
                        f"Daily response for {chunk.symbol} has duplicate date {bar.date.isoformat()}"
                    )
                seen.add(bar.date)
                rows.append(
                    CachedDailyBar(
                        symbol=chunk.symbol,
                        date=bar.date,
                        close=bar.close,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        volume=bar.volume,
                        market_cap=bar.market_cap,
                        provenance=provenance,
                    ).model_dump(mode="json")
                )
            write_cache(
                chunk.symbol,
                "daily",
                cache_dir,
                rows,
                [DateSpan(start=chunk.start, end=chunk.end)],
            )
        else:
            broker = client.fetch_broker_summary(chunk.symbol, chunk.start, chunk.end)
            if broker.symbol.removesuffix(".JK").upper() != chunk.symbol.upper():
                raise SectorsSchemaError(
                    f"Broker response symbol does not match requested symbol {chunk.symbol}"
                )
            if broker.start != chunk.start or broker.end != chunk.end:
                raise SectorsSchemaError(
                    f"Broker response range does not match requested range for {chunk.symbol}"
                )
            rows = []
            seen = set()
            for day in broker.data:
                if broker.symbol.removesuffix(".JK").upper() != chunk.symbol.upper():
                    raise SectorsSchemaError(
                        f"Broker response symbol does not match requested symbol {chunk.symbol}"
                    )
                if not chunk.start <= day.date <= chunk.end:
                    raise SectorsSchemaError(
                        f"Broker response for {chunk.symbol} has a row outside the requested range"
                    )
                if day.date in seen:
                    raise SectorsSchemaError(
                        f"Broker response for {chunk.symbol} has duplicate date {day.date.isoformat()}"
                    )
                seen.add(day.date)
                rows.append(
                    CachedBrokerSummaryDay(
                        symbol=chunk.symbol,
                        date=day.date,
                        summary=day.summary,
                        provenance=provenance,
                    ).model_dump(mode="json")
                )
            write_cache(
                chunk.symbol,
                "broker",
                cache_dir,
                rows,
                [DateSpan(start=chunk.start, end=chunk.end)],
            )
        credits_spent += chunk.estimated_credits
        log_stage(
            logger,
            "fetch",
            status="ok",
            symbol=chunk.symbol,
            data_type=chunk.data_type,
            start=chunk.start.isoformat(),
            end=chunk.end.isoformat(),
            rows=len(rows),
        )
    return SyncReport(
        mode="fetch",
        index=plan.index,
        symbols=plan.symbols,
        chunks_planned=len(plan.chunks),
        credits_spent=credits_spent,
        status="ok",
    )
