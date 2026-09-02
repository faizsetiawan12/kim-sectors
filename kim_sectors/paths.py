"""Filesystem paths used by KIM Sectors."""

from __future__ import annotations

from pathlib import Path


def ensure_dirs(*, cache_dir: Path, output_dir: Path, log_dir: Path = Path("output/logs")) -> None:
    """Create operational directories explicitly when a command starts."""
    for directory in (cache_dir, output_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)
