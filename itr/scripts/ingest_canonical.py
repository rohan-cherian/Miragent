"""
Task 13 (+ 14/15/17 wiring) — ingest src_gmail.message rows into
itr360.message, through the real pipeline: normalise -> identity ->
correlation -> persist -> chunk/embed/index, with failures quarantined
instead of dropped.

Usage:
  poetry run python scripts/ingest_canonical.py
  poetry run python scripts/ingest_canonical.py --dry-run
  poetry run python scripts/ingest_canonical.py --case-id <gmail-thread-id>

ASSUMPTION: reads src_gmail.message, Task 5's re-grain (Rohan's side),
which does not exist yet in this workspace as of writing this script.
Running this against a database without that table/schema will raise
a normal "relation does not exist" error at the SELECT step below —
expected until Task 5 lands, not something this script papers over.

KNOWN LANDMINE, documented not fixed: normalise_message() reads
src_row["connector_run_id"] (scout/canonical/normalise/gmail.py).
If the source rows lack that column (e.g. a differently-shaped
tickets table), every record raises KeyError -> quarantined as
GM-ERR-1001, and the run ends with persisted=0 failed=len(rows).
That is the correct, visible behaviour for a genuinely wrong source
shape — not something this script should guess around — but it looks
identical to an empty mailbox unless you read the counts, so the
summary line below prints an explicit hint when every record fails.

--case-id is a permanent CLI contract. Case correlation (Task 15) now
exists, but this still filters src_gmail.message by Gmail thread_id
rather than a resolved case_id — thread_id is knowable before any of
the pipeline below has run, which is what makes it useful as a
"reprocess just this thread" filter. See _fetch_unprocessed_rows().

DRY RUN POLICY: normalise() and identity resolution
(waterfall.resolve()) are read-mostly — resolve() only ever writes a
harmless identity_unresolved_queue row plus its own decision_audit
row, never a case or a message. Case correlation and message persist
are not: find_or_create_case() commits real itr360.case_ / case_event
/ decision_audit rows of its own, and persisting a message is exactly
the side effect --dry-run promises not to have. So --dry-run runs
normalise + identity resolution only, prints the resolved band for
each record, and stops there — no case, no message, no Qdrant write,
no quarantine row. It never reaches the chunk/embed/index step at
all, so it can never call embed_chunks() (which spends OpenAI money
and writes its own audit rows) by construction, not by a special case
guarding it.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from scout.canonical import quarantine
from scout.canonical.correlation import find_or_create_case
from scout.canonical.identity.waterfall import resolve
from scout.canonical.models import Message
from scout.canonical.normalise.gmail import SOURCE_SYSTEM, normalise_message
from scout.config import settings
from scout.context.chunk import chunk_message
from scout.context.embed import embed_chunks, upsert_chunks
from scout.governance.pii import RedactionError

LOG_PREFIX = "[ingest]"


class IndexingError(RuntimeError):
    """Chunk/embed/index failed for an already-persisted message.

    Distinct from every other per-record failure: by the time this can
    be raised, the itr360.message row already committed successfully
    (see the [FIXED] "commit before indexing" note below) — an index
    failure must never roll that back, only get quarantined on its
    own.
    """


@dataclass
class IngestRun:
    """One run object satisfying both duck types this script needs:
    waterfall.resolve() wants connector_run_id + is_synthetic
    (waterfall.Run's own shape); quarantine.put() wants
    connector_run_id + source_system. Rather than construct two
    different objects for the same run, one dataclass carries both."""

    connector_run_id: uuid.UUID
    source_system: str = SOURCE_SYSTEM
    is_synthetic: bool = False


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
    ingest_run = IngestRun(connector_run_id=ingest_run_id)
    print(f"{LOG_PREFIX} starting connector run {ingest_run_id} (dry_run={dry_run})")

    engine = create_engine(settings.database_url, future=True)

    try:
        rows = _fetch_unprocessed_rows(engine, thread_id_filter=case_id)
    except Exception as exc:
        print(f"{LOG_PREFIX} FATAL: could not read src_gmail.message: {type(exc).__name__}: {exc}")
        raise

    print(f"{LOG_PREFIX} found {len(rows)} unprocessed message(s)")

    normalised = 0
    persisted = 0
    indexing_failed = 0
    failed = 0

    with Session(engine) as session:
        for row in rows:
            src_message_id = row.get("message_id")

            try:
                print(f"{LOG_PREFIX} redact+normalise message_id={src_message_id}")
                canonical = normalise_message(row)
                normalised += 1

                match = resolve(row, ingest_run)

                if dry_run:
                    print(
                        f"{LOG_PREFIX} DRY RUN message_id={src_message_id} "
                        f"band={match.band} confidence={match.confidence:.2f} "
                        f"person_id={match.person_id} - correlation, persist and "
                        "indexing are skipped on a dry run"
                    )
                    continue

                # Always, even when unresolved: a case can exist with an
                # unknown requester. match.person_id is already None on
                # the unresolved band (waterfall.py), so passing it
                # through is the "no context when unresolved" rule by
                # construction — no extra branching needed here.
                case, reason = find_or_create_case(
                    {**row, "sent_at": canonical["sent_at"]}, match.person_id
                )
                canonical["case_id"] = case.id
                canonical["person_id"] = match.person_id

                message_pk = _persist_message(session, canonical)
                # [FIXED] Commit before indexing — an index failure below
                # must not roll this back.
                session.commit()
                persisted += 1
                print(
                    f"{LOG_PREFIX} persisted message_id={src_message_id} "
                    f"-> itr360.message {message_pk} (case={case.id} reason={reason})"
                )

                try:
                    chunks = chunk_message(
                        {**canonical, "id": message_pk}, org_id=case.org_id
                    )
                    if chunks:
                        upsert_chunks(embed_chunks(chunks))
                        print(
                            f"{LOG_PREFIX} indexed message_id={src_message_id} "
                            f"chunks={len(chunks)}"
                        )
                except Exception as exc:
                    try:
                        raise IndexingError(
                            f"indexing failed for persisted message {message_pk}: "
                            f"{type(exc).__name__}: {exc}"
                        ) from exc
                    except IndexingError as indexing_error:
                        quarantine.put(row, indexing_error, ingest_run)
                        indexing_failed += 1
                        print(
                            f"{LOG_PREFIX} INDEXING FAILED (message persisted, "
                            f"quarantined) message_id={src_message_id}: {indexing_error}"
                        )

            except RedactionError:
                # PII governance is a structural guarantee, not a
                # best-effort one — never swallow this per-record.
                print(f"{LOG_PREFIX} FATAL: redaction failed on message_id={src_message_id} - aborting run")
                raise
            except Exception as exc:
                failed += 1
                session.rollback()
                print(
                    f"{LOG_PREFIX} ERROR message_id={src_message_id}: {type(exc).__name__}: {exc}"
                )
                if not dry_run:
                    quarantine.put(row, exc, ingest_run)
                continue

    print(
        f"{LOG_PREFIX} done - normalised={normalised} persisted={persisted} "
        f"indexing_failed={indexing_failed} failed={failed} dry_run={dry_run}"
    )
    if rows and failed == len(rows):
        print(
            f"{LOG_PREFIX} HINT: every record failed - this usually means "
            "src_gmail.message doesn't have the columns this script expects "
            "(see the KNOWN LANDMINE note in this file's docstring), not that "
            "the mailbox is empty. Check the ERROR lines above."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-id",
        default=None,
        help=(
            "Reprocess only messages for one Gmail thread — filters "
            "src_gmail.message by thread_id, not a resolved itr360.case_.id "
            "(deliberate: thread_id is known before this script's pipeline runs)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run redaction + normalisation + identity resolution and print the "
            "resolved band for each record, but write no case, no message, no "
            "Qdrant data, and no quarantine row."
        ),
    )
    args = parser.parse_args()

    return run(case_id=args.case_id, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
