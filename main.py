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
    CacheError,
    MarketDataError,
    SectorsAuthError,
    SectorsRequestError,
    SectorsSchemaError,
    SectorsMarketData,
    ping_sectors,
    sync_cache,
)
from kim_sectors.backtest import (
    DEFAULT_COST_BPS,
    DEFAULT_REBALANCE_SESSIONS,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_TOP_K,
    run_backtest,
)
from kim_sectors.observability import configure_logging
from kim_sectors.outputs.telegram import TelegramDeliveryError, TelegramSender
from kim_sectors.paths import ensure_dirs
from kim_sectors.strategy import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_MOMENTUM_LOOKBACK,
    rank_momentum,
    rank_signal,
)
from kim_sectors.workflow import run_daily
from kim_sectors.workflow.adapters import (
    build_market_data as default_build_market_data,
    build_telegram_sender as default_build_telegram_sender,
)
from kim_sectors.workflow.command_failures import (
    EXIT_AUTH,
    EXIT_REQUEST,
    EXIT_SCHEMA,
    EXIT_TELEGRAM,
    EXIT_UNEXPECTED,
    translate_command_error,
    unexpected_failure,
)
from kim_sectors.outputs.errors import format_backtest_coverage_error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python main.py")
    commands = parser.add_subparsers(dest="command", required=True)
    ping = commands.add_parser("ping-sectors", help="verify live Sectors market data")
    ping.add_argument("--symbol", default=DEFAULT_PING_SYMBOL)
    ping.add_argument("--window-days", type=int, default=7)
    sync = commands.add_parser("sync-cache", help="resolve universe and sync market data cache")
    sync.add_argument("--start", required=True, type=date.fromisoformat)
    sync.add_argument("--end", required=True, type=date.fromisoformat)
    sync.add_argument("--fetch", action="store_true", default=False)
    sync.add_argument("--refresh-universe", action="store_true", default=False)
    rank = commands.add_parser("rank", help="rank universe by trailing momentum from cache")
    rank.add_argument("--market-date", required=True, type=date.fromisoformat)
    rank.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    signal = commands.add_parser(
        "signal", help="rank universe by Momentum x Broker EV from cache"
    )
    signal.add_argument("--market-date", required=True, type=date.fromisoformat)
    signal.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    signal.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    daily = commands.add_parser(
        "run-daily", help="run the post-market LQ45 pipeline and deliver the daily brief"
    )
    daily.add_argument("--market-date", type=date.fromisoformat, default=None)
    daily.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    daily.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    backtest = commands.add_parser(
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


def main(
    argv: Sequence[str] | None = None,
    *,
    build_market_data: Callable[[SectorsConfig], SectorsMarketData] | None = None,
    build_telegram_sender: Callable[[SectorsConfig], TelegramSender] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    today: Callable[[], date] | None = None,
) -> int:
    """Run a command and return its shell exit code."""
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

    if args.command == "ping-sectors":
        return _run_ping(
            config,
            args,
            build_market_data=build_market_data,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=today() if today else _today(timezone),
        )

    if args.command == "sync-cache":
        return _run_sync_cache(
            config,
            args,
            build_market_data=build_market_data,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=today() if today else _today(timezone),
        )

    if args.command == "rank":
        return _run_rank(
            config,
            args,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=today() if today else _today(timezone),
        )

    if args.command == "signal":
        return _run_signal(
            config,
            args,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=today() if today else _today(timezone),
        )

    if args.command == "run-daily":
        return _run_daily(
            config,
            args,
            build_market_data=build_market_data,
            build_telegram_sender=build_telegram_sender,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=today() if today else _today(timezone),
        )

    if args.command == "run-backtest":
        return _run_backtest(
            config,
            args,
            stdout=stdout,
            stderr=stderr,
            timezone=timezone,
            today=today() if today else _today(timezone),
        )

    return EXIT_UNEXPECTED


def _run_ping(
    config: SectorsConfig,
    args: argparse.Namespace,
    *,
    build_market_data: Callable[[SectorsConfig], SectorsMarketData] | None,
    stdout: TextIO,
    stderr: TextIO,
    timezone: ZoneInfo,
    today: date,
) -> int:
    """Execute the ping-sectors command."""
    logger = None
    try:
        logger = configure_logging(stdout, timezone)
        ensure_dirs(
            cache_dir=config.kim_sectors_cache_dir,
            output_dir=config.kim_sectors_output_dir,
        )
        client = default_build_market_data(config, build_market_data)
        ping_sectors(
            client,
            symbol=args.symbol,
            window_days=args.window_days,
            timezone=timezone,
            logger=logger,
            today=today,
        )
        return 0
    except (SectorsAuthError, SectorsSchemaError, SectorsRequestError) as error:
        return translate_command_error(error, logger, stderr)
    except (MarketDataError, ValueError) as error:
        return translate_command_error(error, logger, stderr)


def _run_sync_cache(
    config: SectorsConfig,
    args: argparse.Namespace,
    *,
    build_market_data: Callable[[SectorsConfig], SectorsMarketData] | None,
    stdout: TextIO,
    stderr: TextIO,
    timezone: ZoneInfo,
    today: date,
) -> int:
    """Execute the sync-cache command."""
    if args.fetch:
        client = default_build_market_data(config, build_market_data)
        ensure_dirs(
            cache_dir=config.kim_sectors_cache_dir,
            output_dir=config.kim_sectors_output_dir,
        )
    else:
        from kim_sectors.market_data.memory import InMemorySectorsAdapter

        client = InMemorySectorsAdapter()
        # Preview mode: no directories, no Sectors API call needed

    logger = configure_logging(stdout, timezone, event="sector_sync_stage", name="kim_sectors.sync")
    try:
        report = sync_cache(
            client,
            index=config.kim_sectors_universe_index,
            start=args.start,
            end=args.end,
            cache_dir=config.kim_sectors_cache_dir,
            timezone=timezone,
            logger=logger,
            today=today,
            fetch=args.fetch,
            refresh_universe=args.refresh_universe,
        )
        if report.status != "ok":
            return EXIT_UNEXPECTED
        return 0
    except (
        SectorsAuthError,
        SectorsSchemaError,
        SectorsRequestError,
        CacheError,
        MarketDataError,
        ValueError,
    ) as error:
        return translate_command_error(error, logger, stderr)


def _run_rank(
    config: SectorsConfig,
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
    timezone: ZoneInfo,
    today: date,
) -> int:
    """Execute the rank command over validated cache records only."""
    logger = configure_logging(stdout, timezone, event="sector_rank_stage", name="kim_sectors.rank")
    try:
        report = rank_momentum(
            index=config.kim_sectors_universe_index,
            market_date=args.market_date,
            lookback=args.lookback,
            cache_dir=config.kim_sectors_cache_dir,
            logger=logger,
            today=today,
        )
        if report.status != "ok":
            return EXIT_UNEXPECTED
        return 0
    except (CacheError, MarketDataError, ValueError) as error:
        return translate_command_error(error, logger, stderr)


def _run_signal(
    config: SectorsConfig,
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
    timezone: ZoneInfo,
    today: date,
) -> int:
    """Execute the signal command over validated cache records only."""
    logger = configure_logging(stdout, timezone, event="sector_signal_stage", name="kim_sectors.signal")
    try:
        report = rank_signal(
            index=config.kim_sectors_universe_index,
            market_date=args.market_date,
            lookback=args.lookback,
            min_samples=args.min_samples,
            cache_dir=config.kim_sectors_cache_dir,
            logger=logger,
            today=today,
        )
        if report.status != "ok":
            return EXIT_UNEXPECTED
        return 0
    except (CacheError, MarketDataError, ValueError) as error:
        return translate_command_error(error, logger, stderr)


def _run_daily(
    config: SectorsConfig,
    args: argparse.Namespace,
    *,
    build_market_data: Callable[[SectorsConfig], SectorsMarketData] | None,
    build_telegram_sender: Callable[[SectorsConfig], TelegramSender] | None,
    stdout: TextIO,
    stderr: TextIO,
    timezone: ZoneInfo,
    today: date,
) -> int:
    """Execute the run-daily command (live pipeline or manual replay)."""
    market_date = args.market_date if args.market_date is not None else today
    logger = configure_logging(
        stdout, timezone, event="sector_daily_stage", name="kim_sectors.daily"
    )
    try:
        client = default_build_market_data(config, build_market_data)
        sender = default_build_telegram_sender(config, build_telegram_sender)
        run_daily(
            client=client,
            index=config.kim_sectors_universe_index,
            market_date=market_date,
            lookback=args.lookback,
            min_samples=args.min_samples,
            cache_dir=config.kim_sectors_cache_dir,
            output_dir=config.kim_sectors_output_dir,
            timezone=timezone,
            logger=logger,
            today=today,
            sender=sender,
            fetch=market_date == today,
        )
        return 0
    except (
        TelegramDeliveryError,
        SectorsAuthError,
        SectorsSchemaError,
        SectorsRequestError,
        CacheError,
        MarketDataError,
        ValueError,
    ) as error:
        return translate_command_error(error, logger, stderr)


def _run_backtest(
    config: SectorsConfig,
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
    timezone: ZoneInfo,
    today: date,
) -> int:
    """Execute the run-backtest command over validated cache records only."""
    index = args.universe or config.kim_sectors_universe_index
    ensure_dirs(
        cache_dir=config.kim_sectors_cache_dir,
        output_dir=config.kim_sectors_output_dir,
    )
    logger = configure_logging(
        stdout, timezone, event="sector_backtest_stage", name="kim_sectors.backtest"
    )
    try:
        report = run_backtest(
            index=index,
            start=args.start,
            end=args.end,
            lookback=args.lookback,
            min_samples=args.min_samples,
            top_k=args.top_k,
            rebalance_sessions=args.rebalance_sessions,
            cost_bps=args.cost_bps,
            slippage_bps=args.slippage_bps,
            cache_dir=config.kim_sectors_cache_dir,
            logger=logger,
            today=today,
            timezone=timezone,
            output_dir=config.kim_sectors_output_dir,
        )
        if report.status != "ok":
            return unexpected_failure(format_backtest_coverage_error(report), stderr)
        return 0
    except (CacheError, MarketDataError, ValueError) as error:
        return translate_command_error(error, logger, stderr)


if __name__ == "__main__":
    raise SystemExit(main())
