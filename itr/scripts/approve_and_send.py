"""
Task 20/22 — manual test harness for approve-then-dispatch.

Usage:
  poetry run python scripts/approve_and_send.py <case-id>
  poetry run python scripts/approve_and_send.py <case-id> --actor "jane@example.com"

Looks up the case's current ProposedAction, calls submit_decision()
with action="approve" (which itself calls dispatch_write() internally
for approve/approve_edited — see scout/canonical/decisions.py:271-279),
and prints both the resulting RecommendationDecision and the
WriteExecution it produced. This script never calls dispatch_write()
directly: doing so on top of submit_decision()'s own internal call
would create a second WriteExecution row for the same decision. This
is the CLI the spec's TEST section runs by hand for exit criteria 21
and 22 — it exists purely as that harness, not a real operational tool.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scout.canonical.decisions import VersionConflictError, submit_decision
from scout.canonical.models import ProposedAction, RecommendationDecision, WriteExecution
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))


def _latest_proposed_action(session: Session, case_id: uuid.UUID) -> ProposedAction | None:
    """Same query decisions.py:80-86 uses internally — reproduced here
    rather than imported since it's a private (underscore) helper."""
    return session.execute(
        select(ProposedAction)
        .where(ProposedAction.case_id == case_id, ProposedAction.tenant_id == TENANT_ID)
        .order_by(ProposedAction.version.desc(), ProposedAction.observed_at.desc())
    ).scalars().first()


def _latest_decision_for_proposed_action(
    session: Session, proposed_action_id: uuid.UUID
) -> RecommendationDecision | None:
    """Same query decisions.py:88-98 uses internally, reproduced for
    the same reason — used here to detect "already decided" BEFORE
    calling submit_decision(), since submit_decision() rotates the
    proposed action's version_token on every success (decisions.py:257)
    and so would not raise VersionConflictError on a second run against
    the same case; it would just approve again."""
    return session.execute(
        select(RecommendationDecision)
        .where(
            RecommendationDecision.proposed_action_id == proposed_action_id,
            RecommendationDecision.tenant_id == TENANT_ID,
        )
        .order_by(RecommendationDecision.decided_at.desc())
    ).scalars().first()


def _latest_write_execution(session: Session, case_id: uuid.UUID) -> WriteExecution | None:
    """Same query execution.py:75-80 (_latest_write_execution) uses
    internally, reproduced here — submit_decision() returns only the
    decision dict, not the WriteExecution it caused, so the outcome has
    to be looked up separately after the call."""
    return session.execute(
        select(WriteExecution)
        .where(WriteExecution.case_id == case_id, WriteExecution.tenant_id == TENANT_ID)
        .order_by(WriteExecution.observed_at.desc())
    ).scalars().first()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", type=uuid.UUID, help="Case to approve the proposed action for")
    parser.add_argument(
        "--actor", default="manual-harness", help="Name recorded as the approving actor"
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url, future=True)

    with Session(engine) as session:
        proposed_action = _latest_proposed_action(session, args.case_id)
        if proposed_action is None:
            print(f"No proposed action for case {args.case_id} - run triage/resolve first")
            return 1

        existing_decision = _latest_decision_for_proposed_action(session, proposed_action.id)
        if existing_decision is not None:
            print(
                f"Case {args.case_id} already decided: {existing_decision.state} "
                f"by {existing_decision.actor} at {existing_decision.decided_at}"
            )
            return 1

        if_match = proposed_action.version_token

    try:
        result = submit_decision(
            case_id=args.case_id,
            action="approve",
            payload={},
            idempotency_key=str(uuid.uuid4()),
            if_match=if_match,
            actor=args.actor,
        )
    except VersionConflictError as exc:
        # A concurrent reviewer's decision landed between our checks
        # above and this call.
        print(f"Case {args.case_id} already decided: {exc.error} by {exc.by} at {exc.at}")
        return 1
    except ValueError as exc:
        # The no-proposed-action race: gone by the time submit_decision()
        # re-checked internally, after we confirmed it existed above.
        print(str(exc))
        return 1

    print(
        f"Decision:        {result['state']}   (id {result['id']}, actor {result['actor']}, "
        f"decided_at {result['decided_at']}, replay={result['replay']})"
    )

    with Session(engine) as session:
        write_execution = _latest_write_execution(session, args.case_id)

    if write_execution is None:
        print(
            "WARNING: no WriteExecution found for this case after approve - "
            "dispatch_write() was skipped (see the except ImportError branch "
            "at scout/canonical/decisions.py:276)."
        )
    else:
        print(
            f"WriteExecution:  {write_execution.state}  "
            f"suppressed_reason={write_execution.suppressed_reason!r}"
        )
        print(
            f"                 attempts={write_execution.attempts}   "
            f"execution_ref={write_execution.execution_ref}   "
            f"error={write_execution.error}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
