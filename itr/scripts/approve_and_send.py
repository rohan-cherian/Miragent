"""
Task 22 — manual test harness for dispatch_write().

Usage:
  poetry run python scripts/approve_and_send.py --case-id <uuid>

Looks up the case's most recent RecommendationDecision, calls
dispatch_write() for it, and prints the resulting WriteExecution
state. This is the CLI the spec's TEST section runs by hand — it
exists purely as that harness, not a real operational tool.
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

from scout.canonical.execution import dispatch_write
from scout.canonical.models import RecommendationDecision
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))


def _latest_decision_for_case(session: Session, case_id: uuid.UUID) -> RecommendationDecision | None:
    return session.execute(
        select(RecommendationDecision)
        .where(RecommendationDecision.case_id == case_id, RecommendationDecision.tenant_id == TENANT_ID)
        .order_by(RecommendationDecision.decided_at.desc())
    ).scalars().first()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True, type=uuid.UUID, help="Case to dispatch the decision for")
    args = parser.parse_args()

    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as session:
        decision = _latest_decision_for_case(session, args.case_id)

    if decision is None:
        print(f"No RecommendationDecision found for case {args.case_id}")
        return 1

    write_execution = dispatch_write(decision.id)

    print(f"WriteExecution state: {write_execution.state}")
    print(f"  id:                {write_execution.id}")
    print(f"  attempts:          {write_execution.attempts}")
    print(f"  execution_ref:     {write_execution.execution_ref}")
    print(f"  suppressed_reason: {write_execution.suppressed_reason}")
    print(f"  error:             {write_execution.error}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
