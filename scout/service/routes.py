"""Probe and corpus routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from scout.service.corpus import fetch_corpus_stats
from scout.service.deps import DatabaseDep
from scout.service.errors import AppError

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    """
    Liveness probe — process is up.

    Does not check Postgres (use ``/ready`` for that).
    """
    return {"status": "ok"}


@router.get("/ready")
def ready(db: DatabaseDep) -> dict[str, Any]:
    """
    Readiness probe — Postgres is reachable and ``src_zendesk`` exists.
    """
    if not db.ping():
        raise AppError(
            "not_ready",
            "Postgres is not reachable",
            status_code=503,
        )

    try:
        row = db.fetch_one(
            "SELECT 1 AS ok FROM information_schema.tables "
            "WHERE table_schema = 'src_zendesk' AND table_name = 'tickets'"
        )
    except AppError:
        raise AppError(
            "not_ready",
            "src_zendesk.tickets is missing — load the schema dump first",
            status_code=503,
        ) from None

    if not row:
        raise AppError(
            "not_ready",
            "src_zendesk.tickets is missing — load the schema dump first",
            status_code=503,
        )

    return {"status": "ready", "database": "ok", "schema": "src_zendesk"}


@router.get("/corpus/stats")
def corpus_stats(db: DatabaseDep) -> dict[str, Any]:
    """
    Scene 1 live aggregates: tickets, accounts, analysts, channels, date range.

    All values are read from Postgres — never stubs.
    """
    return fetch_corpus_stats(db)
