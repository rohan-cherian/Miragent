"""Factory: Postgres-backed Workday store (live ``src_workday`` data only)."""

from __future__ import annotations

import os
from typing import Any

from scout.emulators.workday.base import WorkdayDataStore
from scout.emulators.workday.postgres_store import PostgresWorkdayStore

# Prefer dedicated DSN; fall back to shared emulator Postgres (same host as Zendesk).
ENV_DATABASE_URL = "WORKDAY_DATABASE_URL"
ENV_FALLBACK_URL = "ZENDESK_DATABASE_URL"

_MISSING_URL_MSG = (
    "Workday emulator requires live Postgres with src_workday. Set "
    f"{ENV_DATABASE_URL} (or {ENV_FALLBACK_URL}) to "
    "postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent "
    "after: docker compose -f docker-compose.zendesk-emulator.yml up -d "
    "&& poetry run python scripts/load_workday_postgres.py"
)


def create_store(*, database_url: str | None = None) -> WorkdayDataStore:
    """
    Build the Postgres store.

    Requires ``database_url``, ``WORKDAY_DATABASE_URL``, or ``ZENDESK_DATABASE_URL``.
    Tests inject ``WorkdayStore`` via ``store=``.
    """
    url = (
        database_url
        if database_url is not None
        else (os.getenv(ENV_DATABASE_URL) or os.getenv(ENV_FALLBACK_URL) or "")
    )
    url = url.strip()
    if not url:
        raise ValueError(_MISSING_URL_MSG)
    return PostgresWorkdayStore(url)


def store_info(store: Any) -> dict[str, str]:
    name = getattr(store, "backend_name", "unknown")
    return {"backend": name, "vendor": "workday"}
