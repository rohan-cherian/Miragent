"""
Postgres bookkeeping for Gmail -> MinIO raw ingestion.

**Not the duplicate guard.** Handover doc section 8 puts that in the bucket:
the object key is fully derived from the Gmail message ID, so a HEAD on that
path before the PUT is a complete duplicate check, and no tracking table is
needed for correctness.

What this table is for:

  * ``already_written`` — a cheap pre-filter so a known message costs no Gmail
    API call. Purely an optimisation; the HEAD still runs before every write.
  * audit — what landed where, how big, how many attachments.
  * ``raw_skipped`` — messages deliberately not stored, so a permanent problem
    stays visible instead of being retried silently forever.
  * the ``history_id`` cursor, which the bucket cannot hold.

Drop this whole schema and the pipeline still never writes a duplicate; it just
re-reads more from Gmail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
# Applied in order. 003 adds the Task 5 four-table grain and migrates older
# databases whose cursor is still called raw_sync_state, so a fresh database
# must run both to match what the code queries. Both files are re-runnable.
SCHEMA_FILES = (
    SCHEMA_DIR / "002_src_gmail_raw.sql",
    SCHEMA_DIR / "003_src_gmail_regrain.sql",
)
# Retained for callers/tests that reference the ledger's own DDL directly.
SCHEMA_SQL = SCHEMA_FILES[0]


@dataclass
class RawSyncState:
    account_id: str
    history_id: str | None = None
    backfill_done: bool = False
    backfill_page_token: str | None = None
    last_synced_at: datetime | None = None
    watch_expiration_ms: int | None = None


class GmailRawLedger:
    """Audit trail + incremental cursor for the raw pipeline."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.strip()

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            for path in SCHEMA_FILES:
                conn.execute(path.read_text(encoding="utf-8"))
            conn.commit()

    # ── pre-filter (optimisation only) ────────────────────────────────────────

    def already_written(self, account_id: str, message_ids: list[str]) -> set[str]:
        """
        Subset of ``message_ids`` this ledger has already recorded.

        Used to skip Gmail fetches. The bucket HEAD remains the authority, so a
        stale or empty answer here costs quota, never correctness.
        """
        if not message_ids:
            return set()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT gmail_message_id
                FROM src_gmail.raw_objects
                WHERE account_id = %s AND gmail_message_id = ANY(%s)
                """,
                (account_id, list(message_ids)),
            ).fetchall()
        return {r["gmail_message_id"] for r in rows}

    # ── audit ─────────────────────────────────────────────────────────────────

    def record_written(
        self,
        *,
        account_id: str,
        gmail_message_id: str,
        gmail_thread_id: str | None,
        object_key: str,
        partition: date,
        content_sha256: str,
        size_bytes: int,
        internal_date_ms: int | None,
        attachment_count: int,
    ) -> None:
        """Record a confirmed write. Idempotent — re-recording just refreshes."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO src_gmail.raw_objects (
                    account_id, gmail_message_id, gmail_thread_id, object_key,
                    partition_date, content_sha256, size_bytes,
                    internal_date_ms, attachment_count, written_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (account_id, gmail_message_id) DO UPDATE SET
                    gmail_thread_id  = EXCLUDED.gmail_thread_id,
                    object_key       = EXCLUDED.object_key,
                    partition_date   = EXCLUDED.partition_date,
                    content_sha256   = EXCLUDED.content_sha256,
                    size_bytes       = EXCLUDED.size_bytes,
                    internal_date_ms = EXCLUDED.internal_date_ms,
                    attachment_count = EXCLUDED.attachment_count,
                    written_at       = now()
                """,
                (
                    account_id,
                    gmail_message_id,
                    gmail_thread_id,
                    object_key,
                    partition,
                    content_sha256,
                    size_bytes,
                    internal_date_ms,
                    attachment_count,
                ),
            )
            conn.commit()

    def record_skipped(
        self,
        *,
        account_id: str,
        gmail_message_id: str | None,
        reason: str,
        detail: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO src_gmail.raw_skipped (
                    account_id, gmail_message_id, reason, detail
                ) VALUES (%s, %s, %s, %s)
                """,
                (account_id, gmail_message_id, reason[:200], detail[:2000]),
            )
            conn.commit()

    def get(self, account_id: str, gmail_message_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM src_gmail.raw_objects
                WHERE account_id = %s AND gmail_message_id = %s
                """,
                (account_id, gmail_message_id),
            ).fetchone()
        return dict(row) if row else None

    # ── cursor ────────────────────────────────────────────────────────────────

    def get_state(self, account_id: str) -> RawSyncState | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM src_gmail.sync_state WHERE account_id = %s",
                (account_id,),
            ).fetchone()
        if not row:
            return None
        return RawSyncState(
            account_id=row["account_id"],
            history_id=row.get("history_id"),
            backfill_done=bool(row.get("backfill_done")),
            backfill_page_token=row.get("backfill_page_token"),
            last_synced_at=row.get("last_synced_at"),
            watch_expiration_ms=row.get("watch_expiration_ms"),
        )

    def save_state(self, state: RawSyncState) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO src_gmail.sync_state (
                    account_id, history_id, backfill_done,
                    backfill_page_token, last_synced_at, watch_expiration_ms
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (account_id) DO UPDATE SET
                    history_id = EXCLUDED.history_id,
                    backfill_done = EXCLUDED.backfill_done,
                    backfill_page_token = EXCLUDED.backfill_page_token,
                    last_synced_at = EXCLUDED.last_synced_at,
                    watch_expiration_ms = EXCLUDED.watch_expiration_ms
                """,
                (
                    state.account_id,
                    state.history_id,
                    state.backfill_done,
                    state.backfill_page_token,
                    state.last_synced_at or datetime.now(timezone.utc),
                    state.watch_expiration_ms,
                ),
            )
            conn.commit()

    # ── reporting ─────────────────────────────────────────────────────────────

    def counts(self, account_id: str) -> dict[str, int]:
        with self.connect() as conn:
            written = conn.execute(
                "SELECT COUNT(*) AS n FROM src_gmail.raw_objects WHERE account_id = %s",
                (account_id,),
            ).fetchone()["n"]
            skipped = conn.execute(
                "SELECT COUNT(*) AS n FROM src_gmail.raw_skipped WHERE account_id = %s",
                (account_id,),
            ).fetchone()["n"]
        return {"written": int(written), "skipped": int(skipped)}

    def recent(self, account_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT gmail_message_id, object_key, size_bytes,
                       attachment_count, written_at
                FROM src_gmail.raw_objects
                WHERE account_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (account_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_skips(self, account_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT gmail_message_id, reason, detail, seen_at
                FROM src_gmail.raw_skipped
                WHERE account_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (account_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]
