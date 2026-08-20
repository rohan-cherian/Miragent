"""
Task 23 (test half) — audit completeness across the real pipeline.

Every module already proves its own audit.write() calls are correct in
isolation (Task 14/15/19a/19b/20/22 each have their own suite for
that). What none of those prove, and what this test exists for, is
that one case's audit rows collectively tell one coherent, traceable
story: "how did this case get to where it is" — the whole reason
itr360.decision_audit is append-only in the first place.

No orchestrator wires normalise -> identity -> correlation -> persist
-> triage -> resolve -> decisions -> execution end-to-end yet
(scripts/ingest_canonical.py still skips persist pending case
correlation — Task 13's documented scope decision), so this test
drives the real per-stage functions by hand, the same way
tests/canonical/ and tests/agents/ already build their fixture data.
Only reasoning.complete() is mocked (never a live LLM call); every
other stage — identity, correlation, triage, resolve, decisions,
execution — runs its real, unmocked function against a live database
(and, for triage/resolve, a live Qdrant).

Skips cleanly (pytest.skip()) if there's no live database, no live
Qdrant, or the Task 11 persona seed data isn't present — consistent
with every other integration test in this project
(tests/canonical/test_identity.py, tests/context/test_pack.py).
Weakening this into something that can pass with no real database
would defeat its entire point.

── Why the pipeline lands in low_context, and why that's fine ────────
A fresh, never-indexed case_id guarantees retrieve()'s case_id filter
returns zero Qdrant hits (whatever else already lives in the shared
collection from other test runs), so compile_pack() legitimately
returns low_context=True at both the triage and resolve stage. Per
Task 18/19a's own design this is a normal outcome, not a workaround —
"Empty citations -> low_context=True, empty-but-valid pack, no
exception" — and both agents' abstention paths still persist a real
row and write exactly one audit row each. reasoning.complete() is
monkeypatched to raise if it's ever called at all, so this also
re-proves (inside the real end-to-end chain, not just in isolation)
that the abstention path never reaches the model.

── STEP 1 finding: two real gaps in what audit.timeline(case_id) can show ──

1. Task 12's pii.redact() (governance gate one) never calls
   audit.write() anywhere — grepped scout/governance/pii.py directly;
   no match. category="redaction" (a VALID_CATEGORIES member in
   scout/governance/audit.py) is not used ANYWHERE in this codebase.
   Redaction is therefore invisible to decision_audit entirely, not
   just to a per-case timeline. Not asserted on below — there is
   nothing to assert.

2. scout.canonical.identity.waterfall.resolve()'s _audit_resolution()
   always writes case_id=None ("no case exists yet at this point in
   the pipeline" — identity resolution runs before find_or_create_case
   has produced a case at all). That means the identity_resolution row
   is STRUCTURALLY invisible to audit.timeline(case_id), even though
   identity resolution is the first stage of the very story an
   auditor would want reconstructed for a case. This is real and
   worth fixing (a later task's problem, out of scope here) — not
   something this test can paper over. It's verified below via
   audit.list(category="identity") filtered by this run's own
   thread_id instead of via timeline(case_id).

── STEP 1 inventory: real (category, action) pairs asserted below ────
    scout/canonical/correlation.py    -> ("scan",     "case_correlation")
    scout/agents/triage.py            -> ("system",   "triage")
    scout/agents/resolve.py           -> ("system",   "recommendation_generated")
    scout/canonical/decisions.py      -> ("approval", "submit_decision")
    scout/canonical/execution.py      -> ("approval", "write_suppressed")   [draft_only]
    scout/canonical/identity/waterfall.py -> ("identity", "identity_resolution")  [case_id=None — see finding 2]
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.agents import reasoning
from scout.agents.resolve import recommend
from scout.agents.triage import triage
from scout.canonical.correlation import find_or_create_case
from scout.canonical.decisions import submit_decision
from scout.canonical.identity.waterfall import Run, resolve
from scout.canonical.models import (
    Case,
    CaseEvent,
    Message,
    PersonEmailAlias,
    ProposedAction,
    RecommendationDecision,
    TriageResult,
    WriteExecution,
)
from scout.config import settings
from scout.governance import audit

TENANT_ID = uuid.UUID(str(settings.tenant_id))

# The five (category, action) pairs a "how did this case get to where
# it is" reconstruction via audit.timeline(case_id) must contain, given
# what Step 2 actually exercises. identity_resolution is deliberately
# NOT in this set — see STEP 1 finding 2 above; it's checked separately.
EXPECTED_TIMELINE_PAIRS = {
    ("scan", "case_correlation"),
    ("system", "triage"),
    ("system", "recommendation_generated"),
    ("approval", "submit_decision"),
    ("approval", "write_suppressed"),
}


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping audit completeness test")
    return engine


def _skip_if_qdrant_unreachable() -> None:
    try:
        QdrantClient(url=settings.qdrant_url).get_collections()
    except Exception:
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url} — skipping audit completeness test")


def _verified_persona_email(engine) -> str:
    """Reuses tests/canonical/test_identity.py's exact precondition: a
    real, seeded, verified PersonEmailAlias to resolve confidently
    against, rather than a synthetic Person this test would have to
    construct (and identity resolution's composite-match path is
    already covered by Task 14's own suite — not what this test is
    for)."""
    for candidate in (settings.persona_1_email, settings.persona_2_email):
        email = (candidate or "").strip()
        if not email:
            continue
        with Session(engine) as session:
            alias = session.execute(
                select(PersonEmailAlias).where(
                    PersonEmailAlias.tenant_id == TENANT_ID,
                    PersonEmailAlias.email == email,
                    PersonEmailAlias.verified.is_(True),
                )
            ).scalar_one_or_none()
        if alias is not None:
            return email
    pytest.skip(
        "No verified persona alias configured — run scripts/seed_personas.py first "
        "(see tests/canonical/test_identity.py)"
    )


def _persist_inbound_message(
    engine, case_id: uuid.UUID, person_id: uuid.UUID | None,
    thread_id: str, src_message_id: str, subject: str, body: str, sent_at: datetime,
) -> None:
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(
            Message(
                id=uuid.uuid4(),
                case_id=case_id,
                person_id=person_id,
                direction="inbound",
                channel="email",
                subject=subject,
                body_redacted=body,
                pii_map={},
                pii_status="clean",
                src_message_id=src_message_id,
                thread_id=thread_id,
                sent_at=sent_at,
                tenant_id=TENANT_ID,
                source_system="gmail",
                is_synthetic=True,
                connector_run_id=uuid.uuid4(),
                observed_at=now,
                valid_from=now,
            )
        )
        session.commit()


def _cleanup(engine, case_id: uuid.UUID) -> None:
    """decision_audit is append-only (Task 23) and never touched here,
    only queried. Everything else this test created is cleaned up.
    Deletion order follows the FK chain, same convention
    tests/canonical/test_decisions.py already established:
    WriteExecution (references RecommendationDecision, NOT NULL, no
    cascade) -> RecommendationDecision -> ProposedAction (references
    TriageResult, nullable, no cascade) -> TriageResult -> Message /
    CaseEvent -> Case. The seeded Person/PersonEmailAlias used for
    identity resolution is real fixture data, not created by this
    test, and is never touched."""
    with Session(engine) as session:
        for row in session.execute(
            select(WriteExecution).where(WriteExecution.case_id == case_id)
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(RecommendationDecision).where(RecommendationDecision.case_id == case_id)
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(ProposedAction).where(ProposedAction.case_id == case_id)
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(TriageResult).where(TriageResult.case_id == case_id)
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(Message).where(Message.case_id == case_id)
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(CaseEvent).where(CaseEvent.case_id == case_id)
        ).scalars().all():
            session.delete(row)
        case = session.get(Case, case_id)
        if case is not None:
            session.delete(case)
        session.commit()


async def _drive_pipeline_through_every_stage(engine, persona_email: str) -> tuple[uuid.UUID, str]:
    """Steps 1-7: one synthetic case, driven through the real per-stage
    functions in sequence. Returns (case_id, thread_id) — thread_id is
    what the identity_resolution audit row is matched against
    separately (see STEP 1 finding 2)."""
    thread_id = f"test-thread-{uuid.uuid4()}"
    src_message_id = f"test-msg-{uuid.uuid4()}"
    now = datetime.now(UTC)
    subject = "Licence key stopped working after renewal"
    body = (
        "My licence key stopped working after the renewal went through. "
        "The build machine cannot sign without it and we ship on Friday."
    )

    src_message = {
        "from_address": persona_email,
        "from_display_name": "Test Sender",
        "thread_id": thread_id,
        "in_reply_to": None,
        "signature_block": None,
        "external_id": src_message_id,
        "subject": subject,
        "sent_at": now,
    }

    # Step 1/2 — identity resolution against real seeded persona data.
    run = Run(connector_run_id=uuid.uuid4(), is_synthetic=True)
    match = resolve(src_message, run)
    assert match.band == "apply", "expected a confident match against a verified persona alias"

    # Step 3 — case correlation produces a real case_id.
    case, reason = find_or_create_case(src_message, match.person_id)
    assert reason == "new_case"

    _persist_inbound_message(
        engine, case.id, match.person_id, thread_id, src_message_id, subject, body, now,
    )

    # Step 4 — triage(). Lands in the low_context abstention path (see
    # module docstring) since nothing is indexed in Qdrant for this
    # fresh case_id; still persists a row and writes one audit row.
    triage_result = await triage(case.id)
    assert triage_result.band == "needs_human_triage"

    # Step 5 — resolve.recommend(). Same low_context abstention path.
    proposed_action = await recommend(case.id, triage_result.id)
    assert proposed_action.status == "draft_pending"

    # Step 6 — submit_decision() approves the (placeholder) draft.
    # NOTE: submit_decision() already calls dispatch_write() internally
    # for "approve"/"approve_edited" (scout/canonical/decisions.py:271-275)
    # — that is Step 7. A second, separate dispatch_write(decision.id)
    # call was deliberately NOT added on top of it: it would just create
    # a redundant second WriteExecution/write_suppressed row for the
    # same decision, proving nothing this one call doesn't already prove.
    decision_result = submit_decision(
        case_id=case.id,
        action="approve",
        payload={},
        idempotency_key=str(uuid.uuid4()),
        if_match=proposed_action.version_token,
        actor="tester",
    )
    assert decision_result["state"] == "approved"

    return case.id, thread_id


async def test_audit_trail_is_complete_and_traceable_across_the_pipeline(monkeypatch):
    engine = _make_engine()
    _skip_if_qdrant_unreachable()
    persona_email = _verified_persona_email(engine)

    async def _model_must_not_be_called(**kwargs):
        raise AssertionError(
            "reasoning.complete() was called — the low_context abstention path "
            "should never reach the model (see module docstring)"
        )

    monkeypatch.setattr(reasoning, "complete", _model_must_not_be_called)

    pipeline_started_at = datetime.now(UTC)
    case_id: uuid.UUID | None = None
    try:
        case_id, thread_id = await _drive_pipeline_through_every_stage(engine, persona_email)

        # ── The per-case story: everything audit.timeline(case_id) can see ──
        rows = audit.timeline(case_id)
        pairs = {(row.category, row.action) for row in rows}

        missing = EXPECTED_TIMELINE_PAIRS - pairs
        assert not missing, (
            f"audit.timeline({case_id}) is missing coverage for {sorted(missing)}; "
            f"got {sorted(pairs)}"
        )

        # One coherent story, not just five unrelated rows: timeline()
        # already orders oldest-first, so the pipeline's real sequence
        # should show up as non-decreasing timestamps.
        timestamps = [row.created_at for row in rows]
        assert timestamps == sorted(timestamps)

        # ── identity_resolution: structurally outside timeline(case_id) ──
        # (STEP 1 finding 2). Verified via audit.list() + this run's own
        # thread_id instead, since case_id=None on every such row.
        identity_rows = audit.list(category="identity", from_ts=pipeline_started_at)
        identity_match = [
            row for row in identity_rows if (row.inputs or {}).get("thread_id") == thread_id
        ]
        assert identity_match, (
            "no identity_resolution audit row found for this run's thread_id — "
            "identity resolution itself did not audit, which is a real bug "
            "(distinct from the case_id=None gap this test otherwise works around)"
        )
        assert identity_match[0].action == "identity_resolution"
        assert identity_match[0].category == "identity"
    finally:
        if case_id is not None:
            _cleanup(engine, case_id)
