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
    SectorsHttpAdapter,
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
from kim_sectors.observability import configure_logging, log_stage
from kim_sectors.paths import ensure_dirs
from kim_sectors.strategy import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_MOMENTUM_LOOKBACK,
    rank_momentum,
    rank_signal,
)

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
    backtest = commands.add_parser(
        "run-backtest", help="replay Momentum x Broker EV over cached history"
    )
    backtest.add_argument("--universe", default=None)
    backtest.add_argument("--start", required=True, type=date.fromisoformat)
    backtest.add_argument("--end", required=True, type=date.fromisoformat)
    backtest.add_argument("--lookback", type=int, default=DEFAULT_MOMENTUM_LOOKBACK)
    backtest.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    backtest.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    backtest.add_argument(
        "--rebalance-sessions", type=int, default=DEFAULT_REBALANCE_SESSIONS
    )
    backtest.add_argument("--cost-bps", type=int, default=DEFAULT_COST_BPS)
    backtest.add_argument("--slippage-bps", type=int, default=DEFAULT_SLIPPAGE_BPS)
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
        factory = build_market_data or SectorsHttpAdapter
        client = factory(config)
        ping_sectors(
            client,
            symbol=args.symbol,
            window_days=args.window_days,
            timezone=timezone,
            logger=logger,
            today=today,
        )
        return 0
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
    if args.start > args.end:
        print("error: --start must be on or before --end", file=stderr)
        return EXIT_UNEXPECTED

    if args.fetch:
        factory = build_market_data or SectorsHttpAdapter
        client = factory(config)
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
    except SectorsAuthError as error:
        log_stage(logger, "auth", status="error")
        print(f"error: authentication failed: {error}", file=stderr)
        return EXIT_AUTH
    except SectorsSchemaError as error:
        log_stage(logger, "validate", status="error")
        print(f"error: response schema invalid: {error}", file=stderr)
        return EXIT_SCHEMA
    except SectorsRequestError as error:
        log_stage(logger, "fetch", status="error")
        print(f"error: Sectors request failed: {error}", file=stderr)
        return EXIT_REQUEST
    except (CacheError, MarketDataError, ValueError) as error:
        print(f"error: {error}", file=stderr)
        return EXIT_UNEXPECTED


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
    if args.lookback < 1:
        print("error: --lookback must be >= 1", file=stderr)
        return EXIT_UNEXPECTED
    if args.market_date > today:
        print("error: --market-date cannot be in the future", file=stderr)
        return EXIT_UNEXPECTED

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
        print(f"error: {error}", file=stderr)
        return EXIT_UNEXPECTED


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
    if args.lookback < 1:
        print("error: --lookback must be >= 1", file=stderr)
        return EXIT_UNEXPECTED
    if args.min_samples < 1:
        print("error: --min-samples must be >= 1", file=stderr)
        return EXIT_UNEXPECTED
    if args.market_date > today:
        print("error: --market-date cannot be in the future", file=stderr)
        return EXIT_UNEXPECTED

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
        print(f"error: {error}", file=stderr)
        return EXIT_UNEXPECTED


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
    if args.start > args.end:
        print("error: --start must be on or before --end", file=stderr)
        return EXIT_UNEXPECTED
    if args.end > today:
        print("error: --end cannot be in the future", file=stderr)
        return EXIT_UNEXPECTED
    if args.lookback < 1:
        print("error: --lookback must be >= 1", file=stderr)
        return EXIT_UNEXPECTED
    if args.min_samples < 1:
        print("error: --min-samples must be >= 1", file=stderr)
        return EXIT_UNEXPECTED
    if args.top_k < 1:
        print("error: --top-k must be >= 1", file=stderr)
        return EXIT_UNEXPECTED
    if args.rebalance_sessions < 1:
        print("error: --rebalance-sessions must be >= 1", file=stderr)
        return EXIT_UNEXPECTED
    if args.cost_bps < 0:
        print("error: --cost-bps must be >= 0", file=stderr)
        return EXIT_UNEXPECTED
    if args.slippage_bps < 0:
        print("error: --slippage-bps must be >= 0", file=stderr)
        return EXIT_UNEXPECTED

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
            missing_symbols = [
                item.symbol
                for item in report.coverage.symbols
                if item.daily_missing or item.broker_missing
            ]
            print(
                "error: cache coverage incomplete for the requested window; "
                "run `sync-cache --start {} --end {} --fetch` to fetch missing "
                "history for: {}".format(
                    args.start.isoformat(),
                    args.end.isoformat(),
                    ", ".join(missing_symbols),
                ),
                file=stderr,
            )
            return EXIT_UNEXPECTED
        return 0
    except (CacheError, MarketDataError, ValueError) as error:
        print(f"error: {error}", file=stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
