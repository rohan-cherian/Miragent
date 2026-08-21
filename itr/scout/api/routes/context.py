"""
Task 24, Part D — GET /cases/{id}/context-pack -> ContextPack.

Calls Task 18's compile() directly — no retrieval/trust logic here. compile()
was built to be called from the pipeline, so its inputs are derived the same
way scout/agents/triage.py derives them (the established pattern):

    query_text = f"{subject}\n\n{latest inbound message body_redacted}"
    acl_tags   = ["tenant:<case.tenant_id>"] (+ "org:<case.org_id>" if set)
    intent     = "console"  (compile() accepts and currently ignores intent)

Documented bridges (contract <-> Task 18 dataclass), same pattern as B/C:
* contract requires `summary` and `generated_at`; the ContextPack dataclass
  has neither (a known Task 18 gap). summary is composed here from the
  pack's own numbers; generated_at is the request time. When Task 18 grows
  the two fields, this route just forwards them.
* citations are emitted via Citation.to_dto() — the exact wire shape.
* an unknown case id returns 404 (contract defines only 200; documented).

COST NOTE: every call embeds the query text (compile -> retrieve ->
embed_query, one OpenAI embeddings request) and runs a live Qdrant search.
That is the contract's semantics — the pack is compiled fresh, not cached.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.api.deps import get_db_session, get_tenant_id
from scout.canonical.models import Case, Message
from scout.context.compile import compile as compile_pack

router = APIRouter()


def _query_text(session: Session, case: Case) -> str:
    """Subject + latest inbound redacted body — triage.py's construction."""
    message = session.execute(
        select(Message)
        .where(Message.case_id == case.id, Message.direction == "inbound")
        .order_by(Message.sent_at.desc())
    ).scalars().first()
    body = message.body_redacted if message is not None else ""
    subject = (message.subject if message is not None else None) or case.subject or ""
    return f"{subject}\n\n{body}".strip()


@router.get("/cases/{id}/context-pack")
def get_case_context_pack(
    id: uuid.UUID,  # noqa: A002 — contract PathId
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> dict[str, Any]:
    case = session.get(Case, id)
    if case is None or case.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="case not found")

    acl_tags = [f"tenant:{case.tenant_id}"]
    if case.org_id:
        acl_tags.append(f"org:{case.org_id}")

    pack = compile_pack(
        intent="console",
        case_id=id,
        query_text=_query_text(session, case),
        acl_tags=acl_tags,
    )

    # Bridge: summary + generated_at are required by the contract but absent
    # from Task 18's dataclass — composed here, forwarded once Task 18 has them.
    #
    # Finding 1 fix: low_context fires for ANY cause of an empty pack, so
    # a fixed "nothing cleared the retrieval floor" string was actively
    # misleading — it sent a prior investigation chasing retrieval scores
    # when the actual cause was a governance-layer withhold. Distinguish
    # the layer the next investigation should start in:
    #   - retrieved_count == 0            -> nothing came back from retrieve()
    #   - citation_coverage == 0.0        -> hits were ok, but the token
    #                                        budget excluded every one of them
    #                                        (citation_coverage defaults to
    #                                        1.0 only when there were zero ok
    #                                        hits to cover — see compile.py)
    #   - trust_filtered                  -> hits arrived but were withheld
    #                                        by the ACL check or isolated as
    #                                        malformed (see trust.py)
    #   - otherwise                       -> hits arrived, none cleared
    #                                        settings.retrieval_floor (or, in
    #                                        the rare unrecoverable case,
    #                                        trust_filter failed closed —
    #                                        that path always also logs via
    #                                        logger.exception in trust.py)
    if pack.low_context:
        if pack.retrieved_count == 0:
            reason = "nothing retrieved — no chunks matched the query"
        elif pack.citation_coverage == 0.0:
            reason = "hit(s) found but excluded by the token budget"
        elif pack.trust_filtered:
            reason = "hit(s) found but withheld (ACL-restricted or malformed input)"
        else:
            reason = "hit(s) found but none cleared the retrieval floor"
        low_context_suffix = f", LOW CONTEXT — {reason}"
    else:
        low_context_suffix = ""

    summary = (
        f"{len(pack.citations)} citation(s), "
        f"coverage {pack.citation_coverage:.2f}, "
        f"~{pack.token_count} tokens"
        + low_context_suffix
    )
    return {
        "case_id": str(pack.case_id),
        "summary": summary,
        "citations": [citation.to_dto() for citation in pack.citations],
        "trust_filtered": pack.trust_filtered,
        "generated_at": datetime.now(UTC).isoformat(),
        # extras the console can use; additionalProperties is not forbidden
        "low_context": pack.low_context,
        "citation_coverage": pack.citation_coverage,
        "token_count": pack.token_count,
        "compile_ms": pack.compile_ms,
        "retrieved_count": pack.retrieved_count,
    }
