"""Raw Sectors API payload builders used by tests.

Payloads here are deliberately plain dicts in the shape Sectors returns.
They are *not* domain models: the adapters and validators decide what is
accepted, so tests can hand malformed shapes straight through the same
code path a live response would take.
"""

from __future__ import annotations

from datetime import date


def daily_bars_payload(symbol: str = "BBCA", *, start: date, end: date) -> list[dict]:
    """Build a plausible ``/daily/{symbol}/`` response body."""
    rows = []
    for day in range((end - start).days + 1):
        d = start.toordinal() + day
        rows.append(
            {
                "symbol": symbol,
                "date": date.fromordinal(d).isoformat(),
                "close": 9400.0 + day * 10.0,
                "open": 9350.0 + day * 10.0,
                "high": 9450.0 + day * 10.0,
                "low": 9300.0 + day * 10.0,
                "volume": 1000000 + day * 5000,
                "market_cap": 100000000000.0,
            }
        )
    return rows


def broker_summary_payload(symbol: str = "BBCA", *, start: date, end: date) -> dict:
    """Build a plausible ``/broker-summary/{symbol}/`` response body."""
    return {
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "data": [
            {
                "date": start.isoformat(),
                "summary": [
                    {
                        "broker_code": "MIR",
                        "bfreq": 120,
                        "blot": 4,
                        "bval": 180000000.0,
                        "bavg_per_share": 45000.0,
                        "sfreq": 90,
                        "slot": 3,
                        "sval": 135000000.0,
                        "savg_per_share": 45000.0,
                        "nlot": 1,
                        "nval": 45000000.0,
                        "navg_per_share": 45000.0,
                    }
                ],
            }
        ],
    }


def malformed_daily_bars_payload() -> list[dict]:
    """A daily-bar body missing the required ``close`` field."""
    return [{"symbol": "BBCA", "date": "2026-08-26", "volume": 1}]


def universe_screener_payload(
    symbols: list[str], *, has_next: bool = False, next_offset: int | None = None
) -> dict:
    """Build one companies-screener page with permissive extra fields."""
    return {
        "results": [{"symbol": symbol, "company_name": "Example"} for symbol in symbols],
        "pagination": {
            "total_count": len(symbols),
            "showing": len(symbols),
            "limit": 30,
            "offset": 0,
            "has_next": has_next,
            "has_previous": False,
            "next_offset": next_offset,
            "previous_offset": None,
        },
    }


def universe_screener_page(
    symbols: list[str], *, offset: int, has_next: bool = False, next_offset: int | None = None
) -> dict:
    """Build a page whose pagination offset matches the request."""
    payload = universe_screener_payload(
        symbols, has_next=has_next, next_offset=next_offset
    )
    payload["pagination"]["offset"] = offset
    return payload


def daily_bars_for_symbol(symbol: str, *, start: date, end: date) -> list[dict]:
    """Build daily bars preserving the requested symbol."""
    return daily_bars_payload(symbol, start=start, end=end)
