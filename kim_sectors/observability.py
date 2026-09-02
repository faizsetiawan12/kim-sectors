"""Small structured logging helpers shared by pipeline stages."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import IO, Any
from zoneinfo import ZoneInfo


class JsonFormatter(logging.Formatter):
    """Format stage records as one JSON object per line."""

    def __init__(self, timezone: ZoneInfo, *, event: str = "sector_ping_stage"):
        super().__init__()
        self.timezone = timezone
        self.event = event

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(self.timezone).isoformat(timespec="seconds"),
            "event": self.event,
            "stage": getattr(record, "stage", "unknown"),
            "status": getattr(record, "status", "ok"),
        }
        payload.update(getattr(record, "details", {}))
        return json.dumps(payload, sort_keys=True)


def configure_logging(
    stream: IO[str],
    timezone: ZoneInfo,
    *,
    event: str = "sector_ping_stage",
    name: str = "kim_sectors.ping",
) -> logging.Logger:
    """Create an isolated logger that writes only structured lines."""
    logger = logging.Logger(name)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(timezone, event=event))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_stage(logger: logging.Logger, stage: str, status: str = "ok", **details: Any) -> None:
    """Write one structured stage record."""
    logger.info(stage, extra={"stage": stage, "status": status, "details": details})
