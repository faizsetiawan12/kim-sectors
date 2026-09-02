"""Thin command interface for KIM Sectors."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from typing import Callable, Sequence, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from kim_sectors.config import SectorsConfig
from kim_sectors.market_data import (
    DEFAULT_PING_SYMBOL,
    MarketDataError,
    SectorsAuthError,
    SectorsHttpAdapter,
    SectorsRequestError,
    SectorsSchemaError,
    SectorsMarketData,
    ping_sectors,
)
from kim_sectors.observability import configure_logging, log_stage
from kim_sectors.paths import ensure_dirs

EXIT_UNEXPECTED = 1
EXIT_AUTH = 2
EXIT_SCHEMA = 3
EXIT_REQUEST = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python main.py")
    commands = parser.add_subparsers(dest="command", required=True)
    ping = commands.add_parser("ping-sectors", help="verify live Sectors market data")
    ping.add_argument("--symbol", default=DEFAULT_PING_SYMBOL)
    ping.add_argument("--window-days", type=int, default=7)
    return parser


def _today(timezone: ZoneInfo) -> date:
    return datetime.now(timezone).date()


def main(
    argv: Sequence[str] | None = None,
    *,
    build_market_data: Callable[[SectorsConfig], SectorsMarketData] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    today: Callable[[], date] | None = None,
) -> int:
    """Run a command and return its shell exit code."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = _parser().parse_args(argv)
    if args.command != "ping-sectors":
        return EXIT_UNEXPECTED

    logger = None
    try:
        config = SectorsConfig()
        try:
            timezone = ZoneInfo(config.kim_sectors_timezone)
        except ZoneInfoNotFoundError as error:
            print(f"error: configuration invalid: {error}", file=stderr)
            return EXIT_UNEXPECTED
        logger = configure_logging(stdout, timezone)
        ensure_dirs(
            cache_dir=config.kim_sectors_cache_dir,
            output_dir=config.kim_sectors_output_dir,
        )
        factory = build_market_data or SectorsHttpAdapter
        client = factory(config)
        ping_sectors(
            client,
            symbol=args.symbol,
            window_days=args.window_days,
            timezone=timezone,
            logger=logger,
            today=today() if today else _today(timezone),
        )
        return 0
    except ValidationError as error:
        if "sectors_api_key" in str(error) or "SECTORS_API_KEY" in str(error):
            message = "error: authentication failed: SECTORS_API_KEY is not set"
            print(message, file=stderr)
            return EXIT_AUTH
        print(f"error: configuration invalid: {error}", file=stderr)
        return EXIT_UNEXPECTED
    except ZoneInfoNotFoundError as error:
        print(f"error: configuration invalid: {error}", file=stderr)
        return EXIT_UNEXPECTED
    except SectorsAuthError as error:
        if logger:
            log_stage(logger, "auth", status="error")
        print(f"error: authentication failed: {error}", file=stderr)
        return EXIT_AUTH
    except SectorsSchemaError as error:
        if logger:
            log_stage(logger, "validate", status="error")
        print(f"error: response schema invalid: {error}", file=stderr)
        return EXIT_SCHEMA
    except SectorsRequestError as error:
        if logger:
            log_stage(logger, "fetch", status="error")
        print(f"error: Sectors request failed: {error}", file=stderr)
        return EXIT_REQUEST
    except (MarketDataError, ValueError) as error:
        print(f"error: {error}", file=stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
