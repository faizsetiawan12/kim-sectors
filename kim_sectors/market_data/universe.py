"""Universe membership resolution and persistence."""

from __future__ import annotations

from datetime import date, datetime
from logging import Logger
from pathlib import Path
from zoneinfo import ZoneInfo

from ..observability import log_stage
from .base import UniverseMarketData
from .cache import save_universe_membership
from .models import UniverseMembership, UniverseResolution

SCHEMA_VERSION = "1"


def resolve_universe(
    client: UniverseMarketData,
    *,
    index: str,
    cache_dir: Path,
    timezone: ZoneInfo,
    effective_date: date,
    logger: Logger,
) -> UniverseMembership:
    """Resolve and persist a validated effective-date universe snapshot."""
    resolution: UniverseResolution = client.fetch_universe(index)
    membership = UniverseMembership(
        index=index,
        symbols=resolution.symbols,
        pages=resolution.pages,
        effective_date=effective_date,
        resolved_at=datetime.now(timezone),
        source=resolution.source,
        schema_version=SCHEMA_VERSION,
    )
    save_universe_membership(cache_dir, membership)
    log_stage(
        logger,
        "universe",
        status="resolved",
        index=index,
        members=len(membership.symbols),
        pages=resolution.pages,
        effective_date=effective_date.isoformat(),
    )
    return membership
