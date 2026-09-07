"""Command failure and exit-code mapping for CLI boundaries."""

from __future__ import annotations

import sys
from logging import Logger
from typing import TextIO

from kim_sectors.market_data import (
    SectorsAuthError,
    SectorsRequestError,
    SectorsSchemaError,
)
from kim_sectors.observability import log_stage
from kim_sectors.outputs.telegram import TelegramDeliveryError

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_AUTH = 2
EXIT_SCHEMA = 3
EXIT_REQUEST = 4
EXIT_TELEGRAM = 5


def unexpected_failure(message: str, stderr: TextIO = sys.stderr) -> int:
    """Print one standard error message and return EXIT_UNEXPECTED."""
    print(f"error: {message}", file=stderr)
    return EXIT_UNEXPECTED


# Compatibility alias for earlier callers.
fail = unexpected_failure


def translate_command_error(
    error: Exception,
    logger: Logger | None,
    stderr: TextIO,
) -> int:
    """Translate domain exceptions at the CLI boundary to documented exit codes."""
    if isinstance(error, SectorsAuthError):
        if logger is not None:
            log_stage(logger, "auth", status="error")
        print(f"error: authentication failed: {error}", file=stderr)
        return EXIT_AUTH
    if isinstance(error, SectorsSchemaError):
        if logger is not None:
            log_stage(logger, "validate", status="error")
        print(f"error: response schema invalid: {error}", file=stderr)
        return EXIT_SCHEMA
    if isinstance(error, SectorsRequestError):
        if logger is not None:
            log_stage(logger, "fetch", status="error")
        print(f"error: Sectors request failed: {error}", file=stderr)
        return EXIT_REQUEST
    if isinstance(error, TelegramDeliveryError):
        print(f"error: telegram delivery failed: {error}", file=stderr)
        return EXIT_TELEGRAM
    return unexpected_failure(str(error), stderr)


# Compatibility alias for earlier callers.
translate_market_data_failure = translate_command_error
