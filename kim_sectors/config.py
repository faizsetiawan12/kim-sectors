"""Runtime configuration loaded from environment and local ``.env``."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SectorsConfig(BaseSettings):
    """Configuration needed by the live market-data adapter."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    sectors_api_key: SecretStr = Field(min_length=1)
    sectors_base_url: str = "https://api.sectors.app/v2/"
    kim_sectors_timezone: str = "Asia/Jakarta"
    kim_sectors_cache_dir: Path = Path("data/cache")
    kim_sectors_output_dir: Path = Path("output/reports")
    kim_sectors_universe_index: str = "lq45"

    @field_validator("sectors_api_key", mode="before")
    @classmethod
    def require_api_key(cls, value: str | SecretStr) -> str | SecretStr:
        """Reject whitespace-only values at the configuration boundary."""
        raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("SECTORS_API_KEY is not set")
        return value

    @property
    def api_key(self) -> str:
        """Return the key only at the HTTP boundary."""
        return self.sectors_api_key.get_secret_value()

    def __str__(self) -> str:
        """Keep accidental configuration output free of secrets."""
        return "SectorsConfig(api_key=<redacted>, timezone={!r})".format(
            self.kim_sectors_timezone
        )
