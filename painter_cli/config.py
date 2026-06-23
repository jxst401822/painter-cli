"""Application configuration via environment variables and .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings for painter-cli, loaded from env vars prefixed PAINTER_."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PAINTER_",
        extra="ignore",
    )

    # PLC connection
    plc_host: str = "10.10.20.244"
    plc_port: int = 502
    write_interval_ms: int = 150

    # Path interpolation
    # Maximum Euclidean distance between consecutive points.
    # Set to 0 to disable interpolation.
    max_step: int = 5

    # Coordinate system
    coord_range: int = 240  # symmetric: [-240, 240]

    @property
    def write_interval_s(self) -> float:
        """Write interval in seconds."""
        return self.write_interval_ms / 1000.0
