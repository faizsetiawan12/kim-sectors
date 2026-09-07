"""Command failure formatting shared by thin CLI command handlers."""

from __future__ import annotations

import sys
from typing import TextIO
from logging import Logger

from kim_sectors.observability import log_stage
from kim_sectors.outputs.errors import format_backtest_coverage_error
from kim_sectors.outputs.telegram import TelegramDeliveryError
from kim_sectors.market_data import (
    SectorsAuthError,
    SectorsRequestError,
    SectorsSchemaError,
)

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_AUTH = 2
EXIT_SCHEMA = 3
EXIT_REQUEST = 4
EXIT_TELEGRAM = 5


def fail(message: str, stderr: TextIO = sys.stderr) -> int:
    """Print one error line and return EXIT_UNEXPECTED."""
    print(f"error: {message}", file=stderr)
    return EXIT_UNEXPECTED


def translate_market_data_failure(
    error: Exception,
    logger: Logger,
    stderr: TextIO,
) -> int:
    """Map a domain exception to its documented exit code and error line."""
    if isinstance(error, SectorsAuthError):
        log_stage(logger, "auth", status="error")
        print(f"error: authentication failed: {error}", file=stderr)
        return EXIT_AUTH
    if isinstance(error, SectorsSchemaError):
        log_stage(logger, "validate", status="error")
        print(f"error: response schema invalid: {error}", file=stderr)
        return EXIT_SCHEMA
    if isinstance(error, SectorsRequestError):
        log_stage(logger, "fetch", status="error")
        print(f"error: Sectors request failed: {error}", file=stderr)
        return EXIT_REQUEST
    if isinstance(error, TelegramDeliveryError):
        print(f"error: telegram delivery failed: {error}", file=stderr)
        return EXIT_TELEGRAM
    return fail(str(error), stderr)
