"""Settings for the console API service (W1-API-01)."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    """
    Console API configuration.

    ``database_url`` must point at the Postgres instance that holds
    ``src_zendesk`` (same DSN as the Zendesk emulator).
    """

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_name: str = "Miragent Console API"
    app_version: str = "0.1.0"
    environment: str = "development"

    # Set via API_DATABASE_URL or constructor kwarg database_url=
    database_url: str = Field(default="", alias="API_DATABASE_URL")

    # Comma-separated origins for the console (Vite default included).
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    def resolved_database_url(self) -> str:
        url = (self.database_url or "").strip()
        if not url:
            url = (os.getenv("API_DATABASE_URL") or "").strip()
        if not url:
            url = (os.getenv("ZENDESK_DATABASE_URL") or "").strip()
        return url

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> ServiceSettings:
    return ServiceSettings()
