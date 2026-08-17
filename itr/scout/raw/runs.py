"""
itr/scout/raw/runs.py — connector run tracking (Task 6).

Every ingestion run opens a ``raw_ingest.runs`` row and stamps its id on every
row it writes, so any record traces back to the run that produced it.

The seven stage names are fixed and shared by every connector, because the
console's Pipeline Scan screen renders them directly: progress bars read
``progress_pct``, the mini-logs read ``log_line``, the timeline reads
``duration_ms``. Log lines are therefore written as human-readable sentences
with counts, not as debug output.

Usage::

    with connector_run("gmail", "backfill", cursor_before=cursor) as run:
        run.stage("connect", 100, "Connected to Gmail as support@example.com")
        ...
        run.messages_written += 1
        run.cursor_after = new_history_id

A clean exit marks the run ``success``; an exception marks it ``failed``,
records the traceback in ``errors``, and re-raises. Counters and cursor are
flushed either way, so a crashed run still shows how far it got.
"""

from __future__ import annotations

import json
import logging
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Iterator
from uuid import UUID

import psycopg

logger = logging.getLogger(__name__)

__all__ = ["STAGES", "Run", "connector_run", "RunStore"]

# Fixed, in pipeline order. The console renders exactly these seven.
STAGES: tuple[str, ...] = (
    "connect",
    "discover",
    "extract",
    "redact",
    "normalise",
    "resolve",
    "index",
)

_TERMINAL = {"success", "failed", "partial"}


class RunStore:
    """Postgres access for run rows. Opens short-lived connections of its own.

    Deliberately separate from the ingestion transaction: a run's bookkeeping
    must survive the failure of the work it is describing. If the two shared a
    transaction, a rollback would erase the record of what went wrong.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.strip()

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url)

    def start(
        self,
        *,
        tenant_id: str,
        source_system: str,
        mode: str,
        cursor_before: str | None,
        started_at: datetime,
    ) -> UUID:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO raw_ingest.runs (
                        tenant_id, source_system, mode, started_at, status, cursor_before
                    ) VALUES (%s, %s, %s, %s, 'running', %s)
                    RETURNING id
                    """,
                    (tenant_id, source_system, mode, started_at, cursor_before),
                )
                run_id = cur.fetchone()[0]
            conn.commit()
        return run_id

    def finish(
        self,
        run_id: UUID,
        *,
        status: str,
        finished_at: datetime,
        cursor_after: str | None,
        messages_seen: int,
        messages_written: int,
        messages_skipped: int,
        errors: list[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE raw_ingest.runs
                   SET status = %s, finished_at = %s, cursor_after = %s,
                       messages_seen = %s, messages_written = %s,
                       messages_skipped = %s, errors = %s::jsonb
                 WHERE id = %s
                """,
                (
                    status,
                    finished_at,
                    cursor_after,
                    messages_seen,
                    messages_written,
                    messages_skipped,
                    json.dumps(errors),
                    run_id,
                ),
            )
            conn.commit()

    def add_stage_event(
        self,
        run_id: UUID,
        *,
        stage: str,
        progress_pct: int,
        log_line: str,
        duration_ms: int | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_ingest.run_stage_event (
                    run_id, stage, progress_pct, log_line, duration_ms
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (run_id, stage, progress_pct, log_line, duration_ms),
            )
            conn.commit()


class Run:
    """Live handle on one connector run.

    Counters are plain attributes so callers can increment them naturally;
    they are flushed to Postgres when the run closes.
    """

    def __init__(self, run_id: UUID, store: RunStore, *, source_system: str, mode: str) -> None:
        self.id = run_id
        self.source_system = source_system
        self.mode = mode
        self.messages_seen = 0
        self.messages_written = 0
        self.messages_skipped = 0
        self.cursor_after: str | None = None
        self.errors: list[dict[str, Any]] = []
        self._store = store
        self._stage_started = perf_counter()

    # ── stage events ─────────────────────────────────────────────────────────

    def stage(self, name: str, pct: int, log_line: str) -> None:
        """Record one pipeline stage event.

        ``duration_ms`` is measured from the previous stage call, which is what
        the console's timeline ("adapter init 5m · crawl 2h") is built from.
        """
        if name not in STAGES:
            raise ValueError(f"unknown stage {name!r}; expected one of {', '.join(STAGES)}")
        now = perf_counter()
        duration_ms = int((now - self._stage_started) * 1000)
        self._stage_started = now
        pct = max(0, min(100, int(pct)))
        try:
            self._store.add_stage_event(
                self.id,
                stage=name,
                progress_pct=pct,
                log_line=log_line,
                duration_ms=duration_ms,
            )
        except Exception:  # pragma: no cover - telemetry must never break a run
            logger.warning("could not record stage event %s for run %s", name, self.id)
        logger.info("[%s] %d%% %s", name, pct, log_line)

    # ── error trail ──────────────────────────────────────────────────────────

    def note_drop(self, external_id: str, reason: str) -> None:
        """Record a message this run deliberately did not write.

        Appended to ``runs.errors`` rather than raised: one unusable message
        must never abort a run over thousands of good ones.
        """
        self.errors.append(
            {
                "external_id": external_id,
                "reason": reason,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.messages_skipped += 1
        logger.info("dropped %s: %s", external_id, reason)

    def note_error(self, reason: str, **detail: Any) -> None:
        """Record a run-level problem that is not tied to one message."""
        entry = {"reason": reason, "at": datetime.now(timezone.utc).isoformat()}
        entry.update(detail)
        self.errors.append(entry)
        logger.warning("run %s: %s", self.id, reason)


@contextmanager
def connector_run(
    source_system: str,
    mode: str,
    cursor_before: str | None = None,
    *,
    database_url: str | None = None,
    tenant_id: str | None = None,
    store: RunStore | None = None,
) -> Iterator[Run]:
    """Open a ``raw_ingest.runs`` row for the duration of one ingestion run.

    Clean exit  -> status ``success``.
    Exception   -> status ``failed``, traceback appended to ``errors``, re-raised.

    ``store`` is injectable so tests can exercise the flow without Postgres.
    """
    from scout.config import settings

    if store is None:
        store = RunStore(database_url or settings.gmail_database_url)
    tenant = tenant_id or settings.tenant_id

    started_at = datetime.now(timezone.utc)
    run_id = store.start(
        tenant_id=tenant,
        source_system=source_system,
        mode=mode,
        cursor_before=cursor_before,
        started_at=started_at,
    )
    run = Run(run_id, store, source_system=source_system, mode=mode)
    logger.info("run %s started (%s, mode=%s)", run_id, source_system, mode)

    status = "success"
    try:
        yield run
    except BaseException as exc:
        status = "failed"
        run.errors.append(
            {
                "reason": "run_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        raise
    finally:
        # Counters and cursor are flushed on both paths — a crashed run must
        # still show how far it got, or crash recovery has nothing to read.
        try:
            store.finish(
                run_id,
                status=status,
                finished_at=datetime.now(timezone.utc),
                cursor_after=run.cursor_after,
                messages_seen=run.messages_seen,
                messages_written=run.messages_written,
                messages_skipped=run.messages_skipped,
                errors=run.errors,
            )
        except Exception:  # pragma: no cover - never mask the original error
            logger.exception("could not finalise run %s", run_id)
        logger.info(
            "run %s %s — seen=%d written=%d skipped=%d",
            run_id,
            status,
            run.messages_seen,
            run.messages_written,
            run.messages_skipped,
        )
