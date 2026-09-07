"""Command workflow handlers and their domain orchestration."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Callable, TextIO
from zoneinfo import ZoneInfo

from kim_sectors.backtest import run_backtest
from kim_sectors.config import SectorsConfig
from kim_sectors.market_data import (
    CacheError,
    MarketDataError,
    SectorsAuthError,
    SectorsMarketData,
    SectorsRequestError,
    SectorsSchemaError,
    ping_sectors,
    sync_cache,
)
from kim_sectors.observability import configure_logging
from kim_sectors.outputs.errors import format_backtest_coverage_error
from kim_sectors.outputs.telegram import TelegramDeliveryError, TelegramSender
from kim_sectors.paths import ensure_dirs
from kim_sectors.strategy import rank_momentum, rank_signal
from kim_sectors.workflow import run_daily
from kim_sectors.workflow.adapters import (
    build_market_data as default_build_market_data,
    build_telegram_sender as default_build_telegram_sender,
)
from kim_sectors.workflow.command_failures import (
    EXIT_UNEXPECTED,
    translate_command_error,
    unexpected_failure,
)


def run_ping(
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


def run_sync_cache(
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


def run_rank(
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


def run_signal(
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


def run_daily_command(
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


def run_backtest_command(
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
