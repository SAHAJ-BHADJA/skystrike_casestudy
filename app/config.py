"""Application settings, loaded from environment / `.env`.

Kept deliberately small: every knob has a safe default so the app boots with no
configuration at all (falling back to bundled sample data when no API key is set).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- JamBase provider ---
    jambase_api_key: str | None = None
    jambase_base_url: str = "https://api.data.jambase.com/v3"

    # --- Caching (request-reduction) ---
    cache_ttl_seconds: int = 300           # event searches: short, data moves
    geo_cache_ttl_seconds: int = 86_400    # city/metro IDs: rarely change

    # --- Upstream resilience ---
    http_timeout_seconds: float = 10.0
    http_max_retries: int = 3

    @property
    def jambase_enabled(self) -> bool:
        """True when a real key is configured; otherwise we serve sample data."""
        return bool(self.jambase_api_key)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so settings are parsed once per process."""
    return Settings()
