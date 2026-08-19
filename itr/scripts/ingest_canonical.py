"""
Task 13 — ingest src_gmail.message rows into itr360.message.

Usage:
  poetry run python scripts/ingest_canonical.py
  poetry run python scripts/ingest_canonical.py --dry-run
  poetry run python scripts/ingest_canonical.py --case-id <gmail-thread-id>

ASSUMPTION: reads src_gmail.message, Task 5's re-grain (Rohan's side),
which does not exist yet in this workspace as of writing this script.
Running this against a database without that table/schema will raise
a normal "relation does not exist" error at the SELECT step below —
expected until Task 5 lands, not something this script papers over.

--case-id is a permanent CLI contract, but case correlation (Task 15)
doesn't exist yet, so for now it filters src_gmail.message by Gmail
thread_id as a reasonable stand-in — see _fetch_unprocessed_rows().

PERSIST IS CURRENTLY A NO-OP. itr360.message.case_id is NOT NULL
(Task 10), and nothing in this workspace can resolve a real case_id
yet — that's identity resolution (Task 14) feeding case correlation
(Task 15), neither of which exist. Real sequencing per the original
spec is normalise -> identity -> correlation -> persist, so until
Task 15 lands, every record is redacted and normalised for real but
never written to itr360.message; each one is logged as skipped
instead. This makes --dry-run and the real (non-dry-run) path behave
identically for now — that's expected, not a bug, and --dry-run stays
in place for when persist becomes real again after Task 15.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from scout.canonical.models import Message
from scout.canonical.normalise.gmail import SOURCE_SYSTEM, normalise_message
from scout.config import settings
from scout.governance.pii import RedactionError

LOG_PREFIX = "[ingest]"


def _fetch_unprocessed_rows(engine, thread_id_filter: str | None) -> list[dict]:
    """Rows in src_gmail.message with no matching itr360.message yet.

    "Unprocessed" = no itr360.message row exists with
    (source_system='gmail', external_id=<src message_id>) — that pair
    is also the upsert key in _persist_message() below, so a message
    can never be ingested twice.
    """
    query = """
        SELECT src.*
        FROM src_gmail.message AS src
        WHERE NOT EXISTS (
            SELECT 1 FROM itr360.message AS m
            WHERE m.source_system = :source_system
              AND m.external_id = src.message_id::text
        )
    """
    params: dict = {"source_system": SOURCE_SYSTEM}

    if thread_id_filter is not None:
        # Stand-in for --case-id until Task 15 (case correlation) exists.
        query += " AND src.thread_id = :thread_id"
        params["thread_id"] = thread_id_filter

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).mappings().all()

    return [dict(row) for row in rows]


def _persist_message(session: Session, canonical: dict) -> uuid.UUID:
    """Upsert on (source_system, external_id) — never insert-only."""
    existing = session.execute(
        select(Message).where(
            Message.source_system == canonical["source_system"],
            Message.external_id == canonical["external_id"],
        )
    ).scalar_one_or_none()

    if existing is None:
        row = Message(id=uuid.uuid4(), **canonical)
        session.add(row)
        session.flush()
        return row.id

    for key, value in canonical.items():
        setattr(existing, key, value)
    session.flush()
    return existing.id


def run(case_id: str | None, dry_run: bool) -> int:
    # This ingest execution is itself a kind of run, with its own id —
    # distinct from (and not a substitute for) the connector_run_id
    # each canonical row carries, which normalise_message() sets from
    # the SOURCE row's own connector_run_id (the Gmail sync run that
    # originally wrote it into src_gmail.message).
    ingest_run_id = uuid.uuid4()
    print(f"{LOG_PREFIX} starting connector run {ingest_run_id} (dry_run={dry_run})")

    engine = create_engine(settings.database_url, future=True)

    try:
        rows = _fetch_unprocessed_rows(engine, thread_id_filter=case_id)
    except Exception as exc:
        print(f"{LOG_PREFIX} FATAL: could not read src_gmail.message: {type(exc).__name__}: {exc}")
        raise

    print(f"{LOG_PREFIX} found {len(rows)} unprocessed message(s)")

    normalised = 0
    skipped_no_case = 0
    persisted = 0
    failed = 0

    with Session(engine) as session:
        for row in rows:
            message_id = row.get("message_id")

            try:
                print(f"{LOG_PREFIX} redact+normalise message_id={message_id}")
                canonical = normalise_message(row)
                normalised += 1

                # Task 14: identity resolution goes here
                # Task 15: case correlation goes here

                if canonical.get("case_id") is None:
                    # itr360.message.case_id is NOT NULL (Task 10). Case
                    # correlation (Task 15) doesn't exist yet, so this is
                    # always true right now — every record stops here
                    # rather than attempting an insert that would fail.
                    # --dry-run and the real path are identical for now
                    # as a result; that's expected until Task 15 lands.
                    skipped_no_case += 1
                    print(
                        f"{LOG_PREFIX} SKIPPING PERSIST: case correlation not yet "
                        f"implemented (Task 15) — message would be: {canonical}"
                    )
                elif dry_run:
                    print(f"{LOG_PREFIX} DRY RUN — would persist message_id={message_id}: {canonical}")
                else:
                    print(f"{LOG_PREFIX} persist message_id={message_id}")
                    _persist_message(session, canonical)
                    session.commit()
                    persisted += 1

                # Task 17: embed/index step goes here

            except RedactionError:
                # PII governance is a structural guarantee, not a
                # best-effort one — never swallow this per-record.
                print(f"{LOG_PREFIX} FATAL: redaction failed on message_id={message_id} — aborting run")
                raise
            except Exception as exc:
                failed += 1
                session.rollback()
                print(
                    f"{LOG_PREFIX} ERROR message_id={message_id}: {type(exc).__name__}: {exc}"
                )
                # TODO Task 16: write to raw_ingest.quarantine here instead of just logging
                continue

    print(
        f"{LOG_PREFIX} done — normalised={normalised} skipped_no_case={skipped_no_case} "
        f"persisted={persisted} failed={failed} dry_run={dry_run}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-id",
        default=None,
        help=(
            "Reprocess only messages for one case. Case correlation (Task 15) doesn't "
            "exist yet, so this currently filters by src_gmail.message.thread_id instead."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run redaction + normalisation and print what would be written, but write nothing.",
    )
    args = parser.parse_args()

    return run(case_id=args.case_id, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
