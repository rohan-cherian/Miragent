"""Postgres store for Gmail → ticket sync (dedup + cursor)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

SCHEMA_SQL = Path(__file__).resolve().parents[2] / "schema" / "002_src_gmail_schema.sql"


@dataclass
class SyncState:
    mailbox: str
    history_id: str | None = None
    last_internal_date_ms: int | None = None
    last_message_id: str | None = None
    last_synced_at: datetime | None = None


@dataclass
class TicketRow:
    ticket_id: int
    gmail_message_id: str
    gmail_thread_id: str
    mailbox: str
    subject: str
    description: str
    from_address: str | None
    to_address: str | None
    bookmark: str | None
    internal_date_ms: int | None
    history_id: str | None
    synced_at: datetime
    created_at: datetime
    inserted: bool = True  # False when skipped as duplicate


class GmailTicketStore:
    """Persist tickets + sync bookmark in ``src_gmail``."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.strip()

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
        # Strip full-line comments, then run each statement
        cleaned_lines: list[str] = []
        for ln in sql.splitlines():
            stripped = ln.strip()
            if not stripped or stripped.startswith("--"):
                continue
            cleaned_lines.append(ln)
        cleaned = "\n".join(cleaned_lines)
        statements = [s.strip() for s in cleaned.split(";") if s.strip()]
        with self.connect() as conn:
            for stmt in statements:
                conn.execute(stmt)
            conn.commit()

    def get_sync_state(self, mailbox: str) -> SyncState | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM src_gmail.sync_state WHERE mailbox = %s",
                (mailbox,),
            ).fetchone()
        if not row:
            return None
        return SyncState(
            mailbox=row["mailbox"],
            history_id=row.get("history_id"),
            last_internal_date_ms=row.get("last_internal_date_ms"),
            last_message_id=row.get("last_message_id"),
            last_synced_at=row.get("last_synced_at"),
        )

    def upsert_sync_state(self, state: SyncState) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO src_gmail.sync_state (
                    mailbox, history_id, last_internal_date_ms,
                    last_message_id, last_synced_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (mailbox) DO UPDATE SET
                    history_id = EXCLUDED.history_id,
                    last_internal_date_ms = EXCLUDED.last_internal_date_ms,
                    last_message_id = EXCLUDED.last_message_id,
                    last_synced_at = EXCLUDED.last_synced_at
                """,
                (
                    state.mailbox,
                    state.history_id,
                    state.last_internal_date_ms,
                    state.last_message_id,
                    state.last_synced_at or datetime.now(timezone.utc),
                ),
            )
            conn.commit()

    def message_exists(self, gmail_message_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM src_gmail.tickets WHERE gmail_message_id = %s",
                (gmail_message_id,),
            ).fetchone()
        return row is not None

    def insert_ticket(
        self,
        *,
        mailbox: str,
        gmail_message_id: str,
        gmail_thread_id: str,
        subject: str,
        description: str,
        from_address: str | None,
        to_address: str | None,
        bookmark: str | None,
        internal_date_ms: int | None,
        history_id: str | None,
    ) -> TicketRow:
        """
        Insert a ticket. On duplicate ``gmail_message_id``, return existing row
        with ``inserted=False`` (no error).
        """
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO src_gmail.tickets (
                    gmail_message_id, gmail_thread_id, mailbox,
                    subject, description, from_address, to_address,
                    bookmark, internal_date_ms, history_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (gmail_message_id) DO NOTHING
                RETURNING *
                """,
                (
                    gmail_message_id,
                    gmail_thread_id,
                    mailbox,
                    subject,
                    description,
                    from_address,
                    to_address,
                    bookmark,
                    internal_date_ms,
                    history_id,
                ),
            ).fetchone()
            if row is None:
                existing = conn.execute(
                    "SELECT * FROM src_gmail.tickets WHERE gmail_message_id = %s",
                    (gmail_message_id,),
                ).fetchone()
                conn.commit()
                assert existing is not None
                return _ticket_from_row(existing, inserted=False)
            conn.commit()
            return _ticket_from_row(row, inserted=True)

    def count_tickets(self, mailbox: str | None = None) -> int:
        with self.connect() as conn:
            if mailbox:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM src_gmail.tickets WHERE mailbox = %s",
                    (mailbox,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM src_gmail.tickets").fetchone()
        return int(row["n"])

    def list_tickets(self, mailbox: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ticket_id, gmail_message_id, subject, from_address,
                       bookmark, created_at
                FROM src_gmail.tickets
                WHERE mailbox = %s
                ORDER BY internal_date_ms DESC NULLS LAST, ticket_id DESC
                LIMIT %s
                """,
                (mailbox, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def _ticket_from_row(row: dict[str, Any], *, inserted: bool) -> TicketRow:
    return TicketRow(
        ticket_id=int(row["ticket_id"]),
        gmail_message_id=row["gmail_message_id"],
        gmail_thread_id=row["gmail_thread_id"],
        mailbox=row["mailbox"],
        subject=row["subject"],
        description=row["description"] or "",
        from_address=row.get("from_address"),
        to_address=row.get("to_address"),
        bookmark=row.get("bookmark"),
        internal_date_ms=row.get("internal_date_ms"),
        history_id=row.get("history_id"),
        synced_at=row["synced_at"],
        created_at=row["created_at"],
        inserted=inserted,
    )
