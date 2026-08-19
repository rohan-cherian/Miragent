"""
Task 15 — case correlation: find_or_create_case().

The product is Issue-to-Resolution, not email-to-vector: a case is
the unit of work and it forms from a conversation, not a message.
Cases are linked via related_case_ids when correlation is uncertain
(reopen-after-window, dedup) — NEVER auto-merged. Merging is close to
unrecoverable in a real support system, and no confidence score
justifies that risk in a POC. See docs/decisions/ADR-003-case-correlation.md.

ASSUMPTION: `src_message` is Task 5/7's shape (Rohan's side), not
verified against real data in this workspace. Expected fields, all
optional except from_email: from_email, thread_id, in_reply_to
(header value, may be absent), subject, sent_at. May be a dict or any
object with these as attributes (same convention as Task 14's
waterfall.py).

connector_run_id isn't part of find_or_create_case()'s signature (no
`run` context is given here, unlike Task 14's resolve()), and the
assumed src_message shape doesn't include one either — this module
generates a fresh uuid4() per call to use as the Provenance
connector_run_id for any case/case_event it creates, treating one
correlation call as its own run.

Must never import scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical import threading
from scout.canonical.models import Case, CaseEvent, CaseStatus
from scout.canonical.normalise.gmail import SOURCE_SYSTEM
from scout.config import settings
from scout.governance.audit import write as audit_write

TENANT_ID = uuid.UUID(str(settings.tenant_id))

_CASE_NUMBER_SEQUENCE = "itr360.case_number_seq"

_EVENT_TYPE_BY_REASON = {
    "same_thread": "case_matched_same_thread",
    "in_reply_to": "case_matched_in_reply_to",
    "reopened": "case_reopened",
    "new_after_window": "case_created_new_after_window",
    "dedup_link": "case_created_dedup_link",
    "new_case": "case_created_new",
}

_engine: Engine | None = None
_sequence_ensured = False


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def _field(src_message, name: str):
    if isinstance(src_message, Mapping):
        return src_message.get(name)
    return getattr(src_message, name, None)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _next_case_number(session: Session) -> str:
    """ITR-{year}-{seq:05d}, backed by a Postgres sequence created on first
    use — a pure numbering utility, not a schema table, so it's created
    here rather than in a migration."""
    global _sequence_ensured
    if not _sequence_ensured:
        session.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {_CASE_NUMBER_SEQUENCE}"))
        _sequence_ensured = True

    seq = session.execute(text(f"SELECT nextval('{_CASE_NUMBER_SEQUENCE}')")).scalar_one()
    year = datetime.now(timezone.utc).year
    return f"ITR-{year}-{seq:05d}"


def _create_case(
    session: Session,
    subject: str | None,
    person_id: uuid.UUID | None,
    sent_at: datetime | None,
    connector_run_id: uuid.UUID,
    related_case_ids: list[uuid.UUID],
) -> Case:
    now = datetime.now(timezone.utc)
    case = Case(
        id=uuid.uuid4(),
        case_number=_next_case_number(session),
        org_id=None,
        requester_id=person_id,
        subject=subject or "(no subject)",
        status=CaseStatus.NEW.value,
        opened_at=sent_at or now,
        reopened_count=0,
        related_case_ids=list(related_case_ids),
        tenant_id=TENANT_ID,
        source_system=SOURCE_SYSTEM,
        is_synthetic=False,
        connector_run_id=connector_run_id,
        observed_at=now,
        valid_from=now,
    )
    session.add(case)
    session.flush()
    return case


def _apply_reopen_or_window_split(
    session: Session,
    case: Case,
    person_id: uuid.UUID | None,
    sent_at: datetime | None,
    connector_run_id: uuid.UUID,
    matched_reason: str,
) -> tuple[Case, str, dict]:
    """A case matched via same_thread/in_reply_to. If it's closed, either
    reopen it (within REOPEN_WINDOW_DAYS) or split into a new case
    linked via related_case_ids (outside the window)."""
    if case.status != CaseStatus.CLOSED.value:
        return case, matched_reason, {}

    window = timedelta(days=settings.reopen_window_days)
    if case.closed_at is not None and sent_at is not None and (sent_at - case.closed_at) <= window:
        case.status = CaseStatus.OPEN.value
        case.reopened_count += 1
        return case, "reopened", {"previously_closed_at": case.closed_at.isoformat()}

    new_case = _create_case(
        session, case.subject, person_id, sent_at, connector_run_id, related_case_ids=[case.id]
    )
    case.related_case_ids = list(case.related_case_ids) + [new_case.id]
    return new_case, "new_after_window", {"linked_case_id": str(case.id)}


def _find_dedup_candidate(
    session: Session, person_id: uuid.UUID, subject: str, sent_at: datetime
) -> Case | None:
    """Rule 4 (dedup_link): same person opened another case within
    DUP_WINDOW_HOURS whose subject scores > 0.85 similar via
    difflib.SequenceMatcher (same approach as Task 14's waterfall.py,
    reused for consistency rather than adding a dependency)."""
    if not subject:
        return None

    window_start = sent_at - timedelta(hours=settings.dup_window_hours)

    candidates = session.execute(
        select(Case).where(
            Case.tenant_id == TENANT_ID,
            Case.requester_id == person_id,
            Case.opened_at >= window_start,
            Case.opened_at <= sent_at,
        )
    ).scalars().all()

    for candidate in candidates:
        if _similarity(subject, candidate.subject) > 0.85:
            return candidate

    return None


def _write_case_event(session: Session, case_id: uuid.UUID, reason: str, extra: dict) -> None:
    session.add(
        CaseEvent(
            id=uuid.uuid4(),
            case_id=case_id,
            event_type=_EVENT_TYPE_BY_REASON[reason],
            payload={"reason": reason, **extra},
            occurred_at=datetime.now(timezone.utc),
            actor="system",
        )
    )


def _write_audit(thread_id, in_reply_to, case_id: uuid.UUID, reason: str) -> None:
    audit_write(
        actor="system",
        action="case_correlation",
        category="scan",
        case_id=case_id,
        inputs={"thread_id": thread_id, "in_reply_to": in_reply_to},
        outputs={"case_id": str(case_id), "reason": reason},
    )


def find_or_create_case(src_message, person_id: uuid.UUID | None) -> tuple[Case, str]:
    """Find the case a message belongs to, or create one, applying the
    five correlation rules in order (see ADR-003): same_thread ->
    in_reply_to -> reopen/new_after_window (if the matched case is
    closed) -> dedup_link (no thread match, similar recent case from
    the same person) -> new_case.

    Every branch writes exactly one itr360.case_event row and one
    decision_audit row (category="scan", action="case_correlation").
    Sets case.requester_id = person_id on any case this call creates,
    so Task 14's retro-link TODO (queue.py) has something to update
    later — this function does not implement that retro-link itself.

    Returns (case, reason) where reason is one of: "same_thread",
    "in_reply_to", "reopened", "new_after_window", "dedup_link",
    "new_case".
    """
    thread_id = _field(src_message, "thread_id")
    in_reply_to = _field(src_message, "in_reply_to")
    subject = _field(src_message, "subject") or ""
    sent_at = _field(src_message, "sent_at")

    connector_run_id = uuid.uuid4()
    engine = _get_engine()

    # expire_on_commit=False: `case` is returned to the caller after this
    # session closes below, so its attributes must stay readable without
    # a live session to lazily refresh from (they'd otherwise raise
    # DetachedInstanceError on first access post-commit).
    with Session(engine, expire_on_commit=False) as session:
        matched_case_id = threading.find_case_by_thread_id(session, thread_id)
        matched_reason = "same_thread"

        if matched_case_id is None:
            matched_case_id = threading.find_case_by_in_reply_to(session, in_reply_to)
            matched_reason = "in_reply_to"

        if matched_case_id is not None:
            matched_case = session.get(Case, matched_case_id)
            case, reason, extra = _apply_reopen_or_window_split(
                session, matched_case, person_id, sent_at, connector_run_id, matched_reason
            )
        else:
            dedup_candidate = (
                _find_dedup_candidate(session, person_id, subject, sent_at)
                if person_id is not None and sent_at is not None
                else None
            )

            if dedup_candidate is not None:
                case = _create_case(
                    session, subject, person_id, sent_at, connector_run_id,
                    related_case_ids=[dedup_candidate.id],
                )
                dedup_candidate.related_case_ids = list(dedup_candidate.related_case_ids) + [case.id]
                reason = "dedup_link"
                extra = {"linked_case_id": str(dedup_candidate.id)}
            else:
                case = _create_case(
                    session, subject, person_id, sent_at, connector_run_id, related_case_ids=[]
                )
                reason = "new_case"
                extra = {}

        _write_case_event(session, case.id, reason, extra)
        session.commit()

    _write_audit(thread_id, in_reply_to, case.id, reason)

    return case, reason
