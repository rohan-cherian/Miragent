"""Factory: Postgres-backed Zendesk store (live ``src_zendesk`` data only)."""

from __future__ import annotations

import os
from typing import Any

from scout.emulators.zendesk.base import TicketStore
from scout.emulators.zendesk.postgres_store import PostgresZendeskStore

# Required for the running emulator — no in-memory demo fallback.
ENV_DATABASE_URL = "ZENDESK_DATABASE_URL"

_MISSING_URL_MSG = (
    "Zendesk emulator requires live Postgres. Set "
    f"{ENV_DATABASE_URL} (or pass database_url=...) to "
    "postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent "
    "after: docker compose -f docker-compose.zendesk-emulator.yml up -d "
    "&& poetry run python scripts/load_zendesk_postgres.py"
)


def create_store(*, database_url: str | None = None) -> TicketStore:
    """
    Build the Postgres store.

    Requires ``database_url`` or ``ZENDESK_DATABASE_URL``. There is no
    in-memory demo path — tests inject ``ZendeskStore`` via ``store=``.
    """
    url = (database_url if database_url is not None else os.getenv(ENV_DATABASE_URL)) or ""
    url = url.strip()
    if not url:
        raise ValueError(_MISSING_URL_MSG)
    return PostgresZendeskStore(url)


def store_info(store: Any) -> dict[str, str]:
    """Small health payload describing which backend is active."""
    name = getattr(store, "backend_name", "unknown")
    return {"backend": name, "vendor": "zendesk"}
