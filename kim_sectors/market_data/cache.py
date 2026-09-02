"""Validated JSON persistence and coverage arithmetic for market data."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .errors import CacheError
from .models import CachedBrokerSummaryDay, CachedDailyBar, DateSpan, UniverseMembership

CACHE_SCHEMA_VERSION = "1"
DAILY_DIR = "daily"
BROKER_DIR = "broker"
UNIVERSE_DIR = "universe"


def _add_days(value: date, days: int) -> date:
    return date.fromordinal(value.toordinal() + days)


def _path(cache_dir: Path, data_type: str, symbol: str) -> Path:
    if data_type not in {DAILY_DIR, BROKER_DIR}:
        raise CacheError(f"Unsupported cache data type: {data_type}")
    return cache_dir / data_type / f"{symbol}.json"


def merge_spans(spans: list[DateSpan]) -> list[DateSpan]:
    """Sort and merge inclusive spans, combining overlaps and adjacency."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda span: span.start)
    merged: list[DateSpan] = [ordered[0]]
    for current in ordered[1:]:
        previous = merged[-1]
        if current.start <= _add_days(previous.end, 1):
            merged[-1] = DateSpan(start=previous.start, end=max(previous.end, current.end))
        else:
            merged.append(current)
    return merged


def missing_spans(requested: DateSpan, covered: list[DateSpan]) -> list[DateSpan]:
    """Return the inclusive portions of *requested* not covered by *covered*."""
    missing: list[DateSpan] = []
    cursor = requested.start
    for span in merge_spans(covered):
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


def read_cache(
    symbol: str, data_type: str, cache_dir: Path
) -> tuple[list[dict[str, Any]], list[DateSpan]]:
    """Read one symbol cache file, returning empty state when absent."""
    path = _path(cache_dir, data_type, symbol)
    if not path.exists():
        return [], []
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("cache record must be an object")
        if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError("unsupported cache schema")
        if payload.get("symbol") != symbol:
            raise ValueError("cache symbol mismatch")
        rows = payload.get("rows")
        raw_spans = payload.get("covered_spans")
        if not isinstance(rows, list) or not isinstance(raw_spans, list):
            raise ValueError("cache requires rows and covered_spans")
        row_model = CachedDailyBar if data_type == DAILY_DIR else CachedBrokerSummaryDay
        validated_rows = [row_model.model_validate(row).model_dump(mode="json") for row in rows]
        spans = []
        for raw in raw_spans:
            if not isinstance(raw, dict):
                raise ValueError("covered span must be an object")
            spans.append(DateSpan.model_validate(raw))
        return validated_rows, merge_spans(spans)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise CacheError(f"Cannot read cache {path}: {error}") from error


def write_cache(
    symbol: str,
    data_type: str,
    cache_dir: Path,
    rows: list[dict[str, Any]],
    covered_spans: list[DateSpan],
) -> None:
    """Merge rows and coverage into one symbol cache file atomically."""
    existing_rows, existing_spans = read_cache(symbol, data_type, cache_dir)
    by_date = {row.get("date"): row for row in existing_rows}
    for row in rows:
        key = row.get("date")
        if not isinstance(key, str):
            raise CacheError(f"Cache row for {symbol} lacks a date")
        if key in by_date and by_date[key] != row:
            raise CacheError(f"Conflicting cached {data_type} row for {symbol} on {key}")
        by_date[key] = row
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "symbol": symbol,
        "rows": [by_date[key] for key in sorted(by_date)],
        "covered_spans": [
            span.model_dump(mode="json")
            for span in merge_spans(existing_spans + covered_spans)
        ],
    }
    path = _path(cache_dir, data_type, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ""
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{symbol}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise CacheError(f"Cannot write cache {path}: {error}") from error


def _universe_path(cache_dir: Path, index: str) -> Path:
    return cache_dir / UNIVERSE_DIR / f"{index}.json"


def load_universe_membership_records(
    index: str, cache_dir: Path
) -> list[UniverseMembership]:
    """Load every versioned membership snapshot for an index."""
    path = _universe_path(cache_dir, index)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
        records = payload if isinstance(payload, list) else [payload]
        return [UniverseMembership.model_validate(record) for record in records]
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise CacheError(f"Cannot read universe cache {path}: {error}") from error


def load_universe_membership(index: str, cache_dir: Path) -> UniverseMembership | None:
    """Return the most recently resolved membership, if any."""
    records = load_universe_membership_records(index, cache_dir)
    if not records:
        return None
    return max(records, key=lambda item: item.resolved_at)


def save_universe_membership(cache_dir: Path, membership: UniverseMembership) -> None:
    """Append a membership snapshot, retaining historical effective dates."""
    path = _universe_path(cache_dir, membership.index)
    existing = [
        record.model_dump(mode="json")
        for record in load_universe_membership_records(membership.index, cache_dir)
    ]
    existing.append(membership.model_dump(mode="json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ""
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{membership.index}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(fd, "w") as handle:
            json.dump(existing, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise CacheError(f"Cannot write universe cache {path}: {error}") from error
