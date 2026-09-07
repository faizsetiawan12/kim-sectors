"""Thin command interface for KIM Sectors."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from typing import Callable, Sequence, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from kim_sectors.backtest import (
    DEFAULT_COST_BPS,
    DEFAULT_REBALANCE_SESSIONS,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_TOP_K,
)
from kim_sectors.config import SectorsConfig
from kim_sectors.market_data import DEFAULT_PING_SYMBOL, SectorsMarketData
from kim_sectors.outputs.telegram import TelegramSender
from kim_sectors.strategy import DEFAULT_MIN_SAMPLES, DEFAULT_MOMENTUM_LOOKBACK
from kim_sectors.workflow import commands
from kim_sectors.workflow.command_failures import (
    EXIT_AUTH,
    EXIT_UNEXPECTED,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python main.py")
    commands_parser = parser.add_subparsers(dest="command", required=True)
    ping = commands_parser.add_parser("ping-sectors", help="verify live Sectors market data")
    ping.add_argument("--symbol", default=DEFAULT_PING_SYMBOL)
    ping.add_argument("--window-days", type=int, default=7)
    sync = commands_parser.add_parser("sync-cache", help="resolve universe and sync market data cache")
    sync.add_argument("--start", required=True, type=date.fromisoformat)
    sync.add_argument("--end", required=True, type=date.fromisoformat)
    sync.add_argument("--fetch", action="store_true", default=False)
    sync.add_argument("--refresh-universe", action="store_true", default=False)
    rank = commands_parser.add_parser("rank", help="rank universe by trailing momentum from cache")
    rank.add_argument("--market-date", required=True, type=date.fromisoformat)
    rank.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    signal = commands_parser.add_parser(
        "signal", help="rank universe by Momentum x Broker EV from cache"
    )
    signal.add_argument("--market-date", required=True, type=date.fromisoformat)
    signal.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    signal.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    daily = commands_parser.add_parser(
        "run-daily", help="run the post-market LQ45 pipeline and deliver the daily brief"
    )
    daily.add_argument("--market-date", type=date.fromisoformat, default=None)
    daily.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    daily.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    backtest = commands_parser.add_parser(
        "run-backtest", help="replay Momentum x Broker EV over cached history"
    )
    backtest.add_argument("--universe", default=None)
    backtest.add_argument("--start", required=True, type=date.fromisoformat)
    backtest.add_argument("--end", required=True, type=date.fromisoformat)
    backtest.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    backtest.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    backtest.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    backtest.add_argument("--rebalance-sessions", type=int, default=DEFAULT_REBALANCE_SESSIONS)
    backtest.add_argument("--cost-bps", type=int, default=DEFAULT_COST_BPS)
    backtest.add_argument("--slippage-bps", type=int, default=DEFAULT_SLIPPAGE_BPS)
    return parser


def _today(timezone: ZoneInfo) -> date:
    return datetime.now(timezone).date()


def _dispatch(
    command: str,
    config: SectorsConfig,
    args: argparse.Namespace,
    *,
    build_market_data: Callable[[SectorsConfig], SectorsMarketData] | None,
    build_telegram_sender: Callable[[SectorsConfig], TelegramSender] | None,
    stdout: TextIO,
    stderr: TextIO,
    timezone: ZoneInfo,
    current_date: date,
) -> int:
    """Dispatch parsed command to corresponding workflow handler."""
    if command == "ping-sectors":
        return commands.run_ping(
            config,
            args,
            build_market_data=build_market_data,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=current_date,
        )
    if command == "sync-cache":
        return commands.run_sync_cache(
            config,
            args,
            build_market_data=build_market_data,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=current_date,
        )
    if command == "rank":
        return commands.run_rank(
            config,
            args,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=current_date,
        )
    if command == "signal":
        return commands.run_signal(
            config,
            args,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=current_date,
        )
    if command == "run-daily":
        return commands.run_daily_command(
            config,
            args,
            build_market_data=build_market_data,
            build_telegram_sender=build_telegram_sender,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=current_date,
        )
    if command == "run-backtest":
        return commands.run_backtest_command(
            config,
            args,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=current_date,
        )
    return EXIT_UNEXPECTED


def main(
    argv: Sequence[str] | None = None,
    *,
    build_market_data: Callable[[SectorsConfig], SectorsMarketData] | None = None,
    build_telegram_sender: Callable[[SectorsConfig], TelegramSender] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    today: Callable[[], date] | None = None,
) -> int:
    """Parse arguments, load configuration, dispatch, and return the shell exit code."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = _parser().parse_args(argv)

    try:
        config = SectorsConfig()
    except ValidationError as error:
        if "sectors_api_key" in str(error) or "SECTORS_API_KEY" in str(error):
            print("error: authentication failed: SECTORS_API_KEY is not set", file=stderr)
            return EXIT_AUTH
        print(f"error: configuration invalid: {error}", file=stderr)
        return EXIT_UNEXPECTED

    try:
        timezone = ZoneInfo(config.kim_sectors_timezone)
    except ZoneInfoNotFoundError as error:
        print(f"error: configuration invalid: {error}", file=stderr)
        return EXIT_UNEXPECTED

    current_date = today() if today else _today(timezone)
    return _dispatch(
        args.command,
        config,
        args,
        build_market_data=build_market_data,
        build_telegram_sender=build_telegram_sender,
        stdout=stdout,
        stderr=stderr,
        timezone=timezone,
        current_date=current_date,
    )


if __name__ == "__main__":
    raise SystemExit(main())
