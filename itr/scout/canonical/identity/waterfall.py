"""
Task 14 — identity waterfall.

'A support system that confidently attaches the wrong person's
manager, assets and history is worse than one that says I am not sure
who this is.' Below IDENTITY_PROBABLE the system attaches nothing —
resolve() never guesses past that line, it queues instead.

This module must never import scout.gmail, scout.connectors, or
googleapiclient (tests/test_layering.py, Task 4) — it only reads
itr360 tables via SQLAlchemy and has no idea how a message got into
the database.

ASSUMPTION: `src_message` is Task 5/7's shape (Rohan's side), not
verified against real data in this workspace. Expected fields, all
optional except from_address: from_address (citext, confirmed against
schema/003_src_gmail_regrain.sql), from_display_name, thread_id (a
uuid FK into src_gmail.thread — str-cast before audit serialization),
signature_block (real column, Task 7 landed — populated rows now feed
the 0.40 signature signal), and external_id (the Gmail messageId,
same dedup key Task 13's
normalise_message() already relies on). `src_message` may be a dict or
any object with these as attributes.

No existing fuzzy-matching dependency (rapidfuzz/thefuzz/fuzzywuzzy) is
in pyproject.toml, so difflib.SequenceMatcher.ratio() (stdlib) is used
for name similarity rather than adding one.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical.identity import queue
from scout.canonical.models import Person, PersonEmailAlias
from scout.config import settings
from scout.governance.audit import write as audit_write

TENANT_ID = uuid.UUID(str(settings.tenant_id))

# A line at the start of a signature block that's just a closing
# salutation, not a name. Simple heuristic — Task 7 (signature
# extraction) may hand back cleaner data later; refine here if so.
_SALUTATION_PREFIXES = (
    "thanks",
    "thank you",
    "regards",
    "best regards",
    "warm regards",
    "kind regards",
    "best",
    "sincerely",
    "cheers",
)

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


@dataclass
class Run:
    """Minimal per-ingest-run context resolve() needs for Provenance.

    A later task wires the real ingest pipeline to construct this;
    scripts/ingest_canonical.py is deliberately NOT wired to this
    module yet (Task 14 only builds the waterfall + queue).
    """

    connector_run_id: uuid.UUID
    is_synthetic: bool = False


@dataclass
class Match:
    person_id: uuid.UUID | None
    confidence: float
    band: str  # "apply" | "probable" | "unresolved"
    evidence: list[dict] = field(default_factory=list)


def _field(src_message, name: str):
    if isinstance(src_message, Mapping):
        return src_message.get(name)
    return getattr(src_message, name, None)


def _band_for(confidence: float) -> str:
    if confidence >= settings.identity_apply:
        return "apply"
    if confidence >= settings.identity_probable:
        return "probable"
    return "unresolved"


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _extract_name_from_signature(signature_block: str | None) -> str | None:
    """First non-salutation, non-empty line of a signature block.

    Simple heuristic: signature blocks typically close with
    "Thanks," / "Regards," on their own line immediately before the
    sender's name. Not robust to every real-world signature — good
    enough for a fuzzy-similarity signal, not a parser to depend on
    elsewhere.
    """
    if not signature_block:
        return None

    for line in signature_block.splitlines():
        candidate = line.strip().strip(",.")
        if not candidate:
            continue
        if candidate.lower() in _SALUTATION_PREFIXES:
            continue
        return candidate

    return None


def _composite_match(
    session: Session, from_display_name: str | None, signature_block: str | None, thread_id
) -> tuple[uuid.UUID | None, float, list[dict]]:
    """Sum weighted signals against every known itr360.person; return the best.

    Takes the caller's own session (resolve()'s single session for the
    whole identity-resolution call) rather than opening a new
    connection — see resolve()'s docstring.
    """
    persons = session.execute(
        select(Person).where(Person.tenant_id == TENANT_ID)
    ).scalars().all()

    signature_name = _extract_name_from_signature(signature_block)

    best_person_id: uuid.UUID | None = None
    best_score = 0.0
    best_evidence: list[dict] = []

    for person in persons:
        score = 0.0
        evidence: list[dict] = []

        if signature_name:
            similarity = _similarity(signature_name, person.display_name)
            weighted = 0.40 * similarity
            score += weighted
            evidence.append(
                {"signal": "signature_name_match", "value": signature_name, "weight": weighted}
            )

        if from_display_name:
            similarity = _similarity(from_display_name, person.display_name)
            weighted = 0.30 * similarity
            score += weighted
            evidence.append(
                {
                    "signal": "from_display_name_match",
                    "value": from_display_name,
                    "weight": weighted,
                }
            )

        # TODO: thread-participation signal (flat 0.25) needs to know
        # whether this person has previously sent/received in
        # thread_id. itr360.message has no thread_id column yet and
        # case_.requester_id isn't populated until Task 15 — nothing
        # queryable to check this against today, so it always
        # contributes 0 for now.

        if score > best_score:
            best_score = score
            best_person_id = person.id
            best_evidence = evidence

    return best_person_id, best_score, best_evidence


def _audit_resolution(from_email, thread_id, person_id, band, confidence, evidence) -> None:
    audit_write(
        actor="system",
        action="identity_resolution",
        category="identity",
        case_id=None,  # no case exists yet at this point in the pipeline
        inputs={"from_address": from_email, "thread_id": thread_id},
        outputs={
            "person_id": str(person_id) if person_id is not None else None,
            "band": band,
            "evidence": evidence,
        },
        confidence=confidence,
    )


def resolve(src_message, run: Run) -> Match:
    """Resolve src_message's sender to a known itr360.person, or queue it.

    Evaluates signals in order, stopping at the first one that
    produces a result: verified alias -> unverified alias -> composite
    fuzzy/participation score. Every call writes exactly one
    identity_resolution audit row via scout.governance.audit.write(),
    regardless of which branch fired.

    CONTRACT: when the returned Match.band == "unresolved", the caller
    must not attach any context (org, history, case data, etc.) to
    this message using Match.person_id — it's None precisely because
    nothing cleared IDENTITY_PROBABLE. This function does not and
    cannot enforce that; it's the caller's responsibility.

    Opens exactly one database session for the whole call (alias
    lookups, composite match, and the queue write if unresolved all
    share it) rather than one per query — scout.governance.audit.write()
    still opens its own connection separately, which is out of scope
    here and fine.
    """
    from_email = _field(src_message, "from_address")  # citext, schema/003
    from_display_name = _field(src_message, "from_display_name")
    # uuid FK into src_gmail.thread — str-cast: it lands in JSONB audit
    # inputs and in queue rows, and a raw UUID is not JSON-serializable.
    raw_thread_id = _field(src_message, "thread_id")
    thread_id = str(raw_thread_id) if raw_thread_id is not None else None
    signature_block = _field(src_message, "signature_block")
    message_id = _field(src_message, "external_id")  # gmail messageId, the dedup key

    engine = _get_engine()

    with Session(engine) as session:
        # Step 1 — verified alias.
        alias = session.execute(
            select(PersonEmailAlias).where(
                PersonEmailAlias.tenant_id == TENANT_ID,
                PersonEmailAlias.email == from_email,
                PersonEmailAlias.verified.is_(True),
            )
        ).scalar_one_or_none()

        if alias is not None:
            confidence = 0.99
            band = _band_for(confidence)
            evidence = [{"signal": "verified_alias", "value": from_email, "weight": 1.0}]
            _audit_resolution(from_email, thread_id, alias.person_id, band, confidence, evidence)
            return Match(person_id=alias.person_id, confidence=confidence, band=band, evidence=evidence)

        # Step 2 — unverified alias.
        alias = session.execute(
            select(PersonEmailAlias).where(
                PersonEmailAlias.tenant_id == TENANT_ID,
                PersonEmailAlias.email == from_email,
                PersonEmailAlias.verified.is_(False),
            )
        ).scalar_one_or_none()

        if alias is not None:
            confidence = 0.85
            band = _band_for(confidence)
            evidence = [{"signal": "unverified_alias", "value": from_email, "weight": 1.0}]
            _audit_resolution(from_email, thread_id, alias.person_id, band, confidence, evidence)
            return Match(person_id=alias.person_id, confidence=confidence, band=band, evidence=evidence)

        # Step 3 — composite score.
        candidate_person_id, composite_score, composite_evidence = _composite_match(
            session, from_display_name, signature_block, thread_id
        )
        band = _band_for(composite_score)

        if band == "unresolved":
            # Step 4 — nothing cleared IDENTITY_PROBABLE; queue for review.
            queue.put(
                src_message_id=str(message_id) if message_id is not None else "",
                sender_email=from_email,
                sender_display=from_display_name,
                best_guess_person_id=candidate_person_id,
                best_confidence=composite_score if composite_score > 0 else None,
                evidence=composite_evidence,
                connector_run_id=run.connector_run_id,
                is_synthetic=run.is_synthetic,
                session=session,
            )
            session.commit()
            _audit_resolution(from_email, thread_id, None, band, composite_score, composite_evidence)
            return Match(person_id=None, confidence=composite_score, band=band, evidence=composite_evidence)

        _audit_resolution(from_email, thread_id, candidate_person_id, band, composite_score, composite_evidence)
        return Match(
            person_id=candidate_person_id,
            confidence=composite_score,
            band=band,
            evidence=composite_evidence,
        )
