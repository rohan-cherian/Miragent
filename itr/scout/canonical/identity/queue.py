"""
Task 14, Part 2 — the human-review queue for identities the waterfall
(scout.canonical.identity.waterfall) couldn't confidently resolve.

Every state transition here writes exactly one audit row via
scout.governance.audit.write() — never reimplemented locally. This
module must never import scout.gmail, scout.connectors, or
googleapiclient (tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import logging
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical.models import Case, IdentityUnresolvedQueue, Message, Person, PersonEmailAlias
from scout.canonical.normalise.gmail import SOURCE_SYSTEM
from scout.config import settings
from scout.governance.audit import write as audit_write

logger = logging.getLogger(__name__)

TENANT_ID = uuid.UUID(str(settings.tenant_id))

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def _get_queue_row(session: Session, queue_id: uuid.UUID) -> IdentityUnresolvedQueue:
    row = session.get(IdentityUnresolvedQueue, queue_id)
    if row is None:
        raise ValueError(f"No identity_unresolved_queue row with id {queue_id}")
    return row


def put(
    src_message_id: str,
    sender_email: str,
    sender_display: str | None,
    best_guess_person_id: uuid.UUID | None,
    best_confidence: float | None,
    evidence: list[dict],
    connector_run_id: uuid.UUID,
    is_synthetic: bool = False,
    session: Session | None = None,
) -> uuid.UUID:
    """Insert one pending identity_unresolved_queue row, return its id.

    connector_run_id isn't in the literal Part 2 signature from the
    Task 14 spec, but IdentityUnresolvedQueue's Provenance mixin
    requires it (NOT NULL) — the spec says to fill it "from whatever
    `run` context is available at the call site in waterfall.py", so
    it's an explicit parameter here rather than something this module
    invents on its own.

    `session` is optional: pass resolve()'s own session to participate
    in its single connection for the whole identity-resolution call
    (the caller then commits) instead of put() opening a second one.
    Leave it unset to have put() open, commit, and close its own
    session — the default when called standalone.
    """
    now = datetime.now(UTC)
    row_id = uuid.uuid4()

    row = IdentityUnresolvedQueue(
        id=row_id,
        src_message_id=src_message_id,
        sender_email=sender_email,
        sender_display=sender_display,
        best_guess_person_id=best_guess_person_id,
        best_confidence=best_confidence,
        evidence=evidence,
        status="pending",
        created_at=now,
        tenant_id=TENANT_ID,
        source_system=SOURCE_SYSTEM,
        is_synthetic=is_synthetic,
        connector_run_id=connector_run_id,
        observed_at=now,
        valid_from=now,
    )

    owns_session = session is None
    context = Session(_get_engine()) if owns_session else nullcontext(session)
    with context as active_session:
        active_session.add(row)
        if owns_session:
            active_session.commit()
        else:
            active_session.flush()

    audit_write(
        actor="system",
        action="identity_queue_enqueued",
        category="identity",
        inputs={"sender_email": sender_email, "src_message_id": src_message_id},
        outputs={
            "queue_id": str(row_id),
            "best_guess_person_id": str(best_guess_person_id) if best_guess_person_id else None,
        },
        confidence=best_confidence,
    )

    return row_id


def list_pending() -> list[IdentityUnresolvedQueue]:
    engine = _get_engine()
    with Session(engine) as session:
        rows = session.execute(
            select(IdentityUnresolvedQueue).where(
                IdentityUnresolvedQueue.tenant_id == TENANT_ID,
                IdentityUnresolvedQueue.status == "pending",
            )
        ).scalars().all()
    return list(rows)


def _retrolink_cases(session: Session, sender_email, person_id: uuid.UUID):
    """Point requester-less cases created for this sender at the now-known person.

    Sender attribution path (the only one queryable today — see the call
    site's comment): identity_unresolved_queue rows for sender_email give
    src_message_ids; itr360.message.src_message_id joins them to cases.
    Cases with a non-null requester_id are left untouched. Returns
    [(case_id, previously_unresolved_since)] for the caller to audit —
    previously_unresolved_since is the earliest queue-row created_at for
    this sender (when the system first knew it did not know who this was).
    """
    queue_rows = session.execute(
        select(IdentityUnresolvedQueue.src_message_id, IdentityUnresolvedQueue.created_at)
        .where(
            IdentityUnresolvedQueue.tenant_id == TENANT_ID,
            IdentityUnresolvedQueue.sender_email == sender_email,
        )
    ).all()
    src_message_ids = {row.src_message_id for row in queue_rows if row.src_message_id}
    if not src_message_ids:
        return []
    unresolved_since = min(
        (row.created_at for row in queue_rows if row.created_at), default=None
    )

    case_ids = {
        row[0]
        for row in session.execute(
            select(Message.case_id).where(Message.src_message_id.in_(src_message_ids))
        ).all()
    }
    if not case_ids:
        return []  # normal outcome — e.g. messages not yet persisted to canonical

    retrolinked = []
    cases = session.execute(
        select(Case).where(
            Case.id.in_(case_ids),
            Case.tenant_id == TENANT_ID,
            Case.requester_id.is_(None),  # never overwrite an existing resolution
        )
    ).scalars().all()
    for case in cases:
        case.requester_id = person_id
        retrolinked.append((case.id, unresolved_since))
    return retrolinked


def resolve_as_candidate(queue_id: uuid.UUID, person_id: uuid.UUID, actor: str) -> None:
    """Confirm a queued sender as an existing person: closes the queue
    row and writes a new verified alias for that sender_email."""
    engine = _get_engine()
    now = datetime.now(UTC)

    with Session(engine) as session:
        queue_row = _get_queue_row(session, queue_id)

        queue_row.status = "resolved"
        queue_row.resolved_by = actor
        queue_row.resolved_at = now

        alias = PersonEmailAlias(
            id=uuid.uuid4(),
            person_id=person_id,
            email=queue_row.sender_email,
            email_kind="personal",
            verified=True,
            verified_by=actor,
            verified_at=now,
            confidence=0.99,
            evidence={
                "method": "queue_resolution",
                "note": "manually resolved from identity_unresolved_queue",
                "queue_id": str(queue_id),
            },
            tenant_id=TENANT_ID,
            source_system=SOURCE_SYSTEM,
            is_synthetic=False,
            connector_run_id=queue_row.connector_run_id,
            observed_at=now,
            valid_from=now,
        )
        session.add(alias)

        # Task 15 retro-link (the long-standing TODO, now implementable —
        # correlation.py populates case_.requester_id, and Task 13's wired
        # ingest creates real cases). itr360.message carries NO sender-email
        # column, so sender attribution goes through this sender's OWN
        # identity_unresolved_queue rows: every queue row for sender_email
        # names a src_message_id; itr360.message.src_message_id joins those
        # to their cases. Only cases whose requester_id is still NULL are
        # touched — an existing resolution is never overwritten.
        retrolinked = _retrolink_cases(session, queue_row.sender_email, person_id)

        session.commit()

    audit_write(
        actor=actor,
        action="identity_queue_resolved",
        category="identity",
        inputs={"queue_id": str(queue_id), "person_id": str(person_id)},
        outputs={"alias_created": True, "cases_retrolinked": len(retrolinked)},
    )

    # One case_retrolinked row PER case, written after commit (this module's
    # established ordering), each guarded so an audit-backend failure warns
    # and never unwinds the committed retro-link (trust.py's pattern).
    for case_id, unresolved_since in retrolinked:
        try:
            audit_write(
                actor=actor,
                action="case_retrolinked",
                category="identity",
                case_id=case_id,
                outputs={
                    "person_id": str(person_id),
                    "previously_unresolved_since": (
                        unresolved_since.isoformat() if unresolved_since else None
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001 — logging failure must not cascade
            logger.warning(
                "resolve_as_candidate: case_retrolinked audit row for case %s "
                "could not be written (%s: %s) — retro-link itself is committed.",
                case_id, type(exc).__name__, exc,
            )


def mark_as_new_actor(queue_id: uuid.UUID, display_name: str, actor: str) -> uuid.UUID:
    """Enrol a queued sender as a brand-new person, with a verified alias."""
    engine = _get_engine()
    now = datetime.now(UTC)

    with Session(engine) as session:
        queue_row = _get_queue_row(session, queue_id)

        person_id = uuid.uuid4()
        person = Person(
            id=person_id,
            org_id=None,
            display_name=display_name,
            primary_email=None,
            job_title=None,
            department=None,
            tenant_id=TENANT_ID,
            source_system=SOURCE_SYSTEM,
            is_synthetic=False,
            connector_run_id=queue_row.connector_run_id,
            observed_at=now,
            valid_from=now,
        )
        session.add(person)
        session.flush()

        alias = PersonEmailAlias(
            id=uuid.uuid4(),
            person_id=person_id,
            email=queue_row.sender_email,
            email_kind="personal",
            verified=True,
            verified_by=actor,
            verified_at=now,
            confidence=0.99,
            evidence={
                "method": "queue_new_actor",
                "note": "manually enrolled as a new person from identity_unresolved_queue",
                "queue_id": str(queue_id),
            },
            tenant_id=TENANT_ID,
            source_system=SOURCE_SYSTEM,
            is_synthetic=False,
            connector_run_id=queue_row.connector_run_id,
            observed_at=now,
            valid_from=now,
        )
        session.add(alias)

        queue_row.status = "resolved"
        queue_row.resolved_by = actor
        queue_row.resolved_at = now

        session.commit()

    audit_write(
        actor=actor,
        action="identity_queue_new_actor",
        category="identity",
        inputs={"queue_id": str(queue_id), "display_name": display_name},
        outputs={"person_id": str(person_id)},
    )

    return person_id


def dismiss(queue_id: uuid.UUID, reason: str, actor: str) -> None:
    """Close a queue row without resolving it to any person. reason is mandatory."""
    if not reason or not reason.strip():
        raise ValueError("dismiss() requires a non-empty reason.")

    engine = _get_engine()

    with Session(engine) as session:
        queue_row = _get_queue_row(session, queue_id)
        queue_row.status = "dismissed"
        queue_row.dismiss_reason = reason
        session.commit()

    audit_write(
        actor=actor,
        action="identity_queue_dismissed",
        category="identity",
        inputs={"queue_id": str(queue_id), "reason": reason},
        outputs={"status": "dismissed"},
    )
