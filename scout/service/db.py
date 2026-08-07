"""Postgres connection helpers for the console API."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from scout.service.errors import AppError


class Database:
    """Thin wrapper around a Postgres DSN (``src_zendesk`` corpus)."""

    def __init__(self, database_url: str) -> None:
        if not database_url or not str(database_url).strip():
            raise AppError(
                "misconfigured",
                "API_DATABASE_URL or ZENDESK_DATABASE_URL must be set",
                status_code=503,
            )
        self.database_url = database_url.strip()

    def connect(self) -> psycopg.Connection:
        try:
            return psycopg.connect(self.database_url, row_factory=dict_row)
        except psycopg.Error as exc:
            raise AppError(
                "database_unavailable",
                "Could not connect to Postgres",
                status_code=503,
                details=str(exc),
            ) from exc

    @contextmanager
    def session(self) -> Generator[psycopg.Connection, None, None]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def ping(self) -> bool:
        """Return True when Postgres accepts a trivial query."""
        try:
            with self.session() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 AS ok")
                    row = cur.fetchone()
                    return bool(row and row.get("ok") == 1)
        except AppError:
            return False
        except Exception:
            return False

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any]:
        with self.session() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                row = cur.fetchone()
                if row is None:
                    raise AppError(
                        "not_found",
                        "Query returned no rows",
                        status_code=404,
                    )
                return dict(row)
