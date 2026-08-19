"""
Task 20, Part 2 — pre-built ahead of Task 24's API app.

scout/api/ doesn't exist yet as a working FastAPI app in this
workspace (Task 24 builds app.py, deps.py, and router wiring). This
file has NO FastAPI dependency and raises no HTTP exceptions — it's a
thin wrapper around scout.canonical.decisions.submit_decision() that
translates its two typed exceptions into plain dicts shaped like the
eventual HTTP error bodies, so Task 24 can mount this as a route with
minimal glue: call handle_submit_decision() and map its return shape
to a response (200 for a decision dict, 409 for an "already_decided"
error dict, 422 for a field-validation error dict).

Not wired into an APIRouter or app instance — just the core logic.
"""

from __future__ import annotations

import uuid

from scout.canonical.decisions import ValidationError, VersionConflictError, submit_decision


def handle_submit_decision(
    case_id: uuid.UUID,
    action: str,
    payload: dict,
    idempotency_key: str,
    if_match: str,
    actor: str,
) -> dict:
    """Same signature as submit_decision(). Returns either the decision
    dict on success, or one of two HTTP-error-shaped dicts:
      - {"error": "already_decided", "by": ..., "at": ...}  (-> 409)
      - {"field": ..., "min": ...}                            (-> 422)
    """
    try:
        return submit_decision(
            case_id=case_id,
            action=action,
            payload=payload,
            idempotency_key=idempotency_key,
            if_match=if_match,
            actor=actor,
        )
    except VersionConflictError as exc:
        return {"error": exc.error, "by": exc.by, "at": exc.at}
    except ValidationError as exc:
        return {"field": exc.field, "min": exc.min}
