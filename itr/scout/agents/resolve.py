"""
Task 19b — resolution drafting. The last agent in Slice 1.

Turns a triaged case into a human-reviewable suggested reply. Nothing here
sends anything: ``approval_required`` is always True, the row lands as
``draft_pending``, and Task 22's ACTION_MODE gate has not even run yet.

Two hard rules, both applied to every sentence before anything is persisted:

**Rule A — cite or withhold.** A sentence only counts as cited if the
``chunk_id`` it references is actually present in *this call's* ContextPack.
An uncitable sentence is not dropped and never gets an invented citation — it
is persisted with ``withheld=True`` and empty ``citation_refs``, so the
console can show "the model wanted to say this but could not back it up."

**Rule B — never claim completed work.** A sentence written in the first
person past tense ("I have reset your password") is forced withheld *even if
Rule A passed*. Being well-cited does not excuse claiming an action that has
not happened. Only the executor may speak in the past tense, and only after it
has actually run. See :func:`claims_completed_action`.

Rule B is checked after Rule A and overrides it. That ordering is the point:
the dangerous output is the confident, well-evidenced sentence that says
something was done.

Layering (Task 4): imports nothing from ``scout.gmail``, ``scout.connectors``
or ``googleapiclient``.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.agents import reasoning
from scout.agents.triage import load_case, load_message
from scout.canonical.models import DecisionState, ProposedAction, TriageResult
from scout.config import settings
from scout.context.compile import compile as compile_pack
from scout.governance import audit

logger = logging.getLogger(__name__)

AGENT_NAME = "resolve"
PROMPT_PATH = Path(__file__).with_name("prompts") / "resolve_v1.md"
_PROMPT_VERSION_RE = re.compile(r"<!--\s*prompt_version:\s*([^\s>]+)\s*-->")

# Same provenance convention triage.py uses for an agent-produced row.
SOURCE_SYSTEM = "agent"

# recommended_action_text is NOT NULL, so it can never be empty — these are
# what goes in when there is nothing publishable to say.
NO_CONTEXT_TEXT = "[No supporting context found — requires manual drafting]"
ALL_WITHHELD_TEXT = "[Every drafted sentence was withheld — requires manual drafting]"

# itr360.proposed_action.status is plain text with no enum of its own; the
# established convention (tests/canonical/test_decisions.py, Task 20's
# submit_decision) is DecisionState. draft_pending is the only defined initial
# state — there is no "needs_human_drafting" member and inventing one would
# break Task 20's state machine. The low-context case is therefore expressed
# through the fields that already mean it: risk="high", confidence=0.0,
# approval_required=True, and a single withheld placeholder sentence.
INITIAL_STATUS = DecisionState.DRAFT_PENDING.value


class ResolveError(RuntimeError):
    """Base class for resolution-drafting failures."""


class ResolutionOutput(BaseModel):
    """Exactly what resolve_v1.md instructs the model to return.

    Note what is *absent*: no ``risk`` field and no ``withheld`` field. Risk is
    computed deterministically from confidence below, and withholding is this
    module's decision, not the model's — same principle as triage.py refusing
    to let the model set ``priority``.

    ``sentences`` is a list of plain dicts rather than a nested model so a
    malformed ``citation_refs`` entry degrades to "uncited" (and therefore
    withheld) instead of failing the whole call.
    """

    resolution_path: str | None = None
    confidence: float = 0.0
    sentences: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class _TriageView:
    id: uuid.UUID
    case_id: uuid.UUID
    message_id: uuid.UUID | None
    category: str | None
    intent_class: str | None
    sub_category: str | None
    band: str | None
    confidence: float | None


@dataclass
class DraftSentence:
    text: str
    citation_refs: list[str]
    withheld: bool
    withheld_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "text": self.text,
            "citation_refs": list(self.citation_refs),
            "withheld": self.withheld,
        }
        if self.withheld_reason:
            record["withheld_reason"] = self.withheld_reason
        return record


# ── Rule B — first-person completed-action detection ──────────────────────
#
# BEST EFFORT, DELIBERATELY OVER-INCLUSIVE. This is pattern matching, not
# comprehension: it cannot catch every phrasing a model might invent, and it
# will occasionally flag a legitimate sentence. That asymmetry is intended —
# a false positive costs one withheld sentence the analyst can still read,
# while a false negative puts "I have already refunded you" in front of a
# customer for something nobody has done. When in doubt, withhold.
#
# Not covered, and known: unusual tenses, non-English phrasing, and
# completed-action claims spread across two sentences.
_COMPLETED_ACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "I have ...", "we had ...", "I already ..."
    re.compile(r"\b(?:i|we)\s+(?:have|has|had|already)\b", re.IGNORECASE),
    # "I've ...", "we've ..." (straight and curly apostrophes)
    re.compile(r"\b(?:i|we)\s*['’]ve\b", re.IGNORECASE),
    # "I reset your password", "we refunded the charge"
    re.compile(
        r"\b(?:i|we)\s+(?:just\s+|now\s+|also\s+)?(?:"
        r"sent|updated|fixed|resolved|reset|created|deleted|refunded|processed|"
        r"completed|issued|applied|enabled|disabled|added|removed|restored|"
        r"renewed|cancell?ed|escalated|contacted|emailed|called|scheduled|"
        r"installed|upgraded|downgraded|configured|changed|corrected|adjusted|"
        r"synchronised|synchronized|actioned|arranged|raised|logged|closed|"
        r"reopened|verified|confirmed|approved|granted|revoked|migrated|"
        r"restarted|rebooted|replaced|refreshed|reactivated|reinstated|"
        r"transferred|credited|extended|amended|attached|forwarded"
        r")\b",
        re.IGNORECASE,
    ),
    # "I went ahead and ...", "we took care of ..."
    re.compile(r"\b(?:i|we)\s+went\s+ahead\b", re.IGNORECASE),
    re.compile(r"\b(?:i|we)\s+took\s+care\s+of\b", re.IGNORECASE),
    # "as requested, I ..." / "per your request we ..."
    re.compile(r"\bas\s+(?:requested|discussed)\b[^.]{0,40}\b(?:i|we)\b", re.IGNORECASE),
    # Passive completed claims — "your licence has been reissued". Not
    # first-person, but the same false promise to the customer.
    re.compile(r"\b(?:has|have)\s+been\s+\w+(?:ed|n)\b", re.IGNORECASE),
)


def claims_completed_action(text: str) -> bool:
    """True when a sentence claims work that has already been done.

    Nothing has been sent or executed at this stage, so any such claim is
    false by construction. See the module comment above for what this pattern
    match can and cannot catch.
    """
    if not text:
        return False
    return any(pattern.search(text) for pattern in _COMPLETED_ACTION_PATTERNS)


# ── Confidence and risk ───────────────────────────────────────────────────


def risk_for(confidence: float) -> str:
    """Confidence -> risk, using the settings named for exactly this.

    high   < settings.reco_medium (0.60) <= medium < settings.reco_high (0.85) <= low

    reco_medium / reco_high are the Task 3 recommendation thresholds, not the
    triage ones. They currently share boundaries with triage_floor (0.60), but
    they are the values calibration will move when recommendation banding
    changes, so this reads them rather than triage_floor/triage_escalate.
    """
    if confidence < settings.reco_medium:
        return "high"
    if confidence < settings.reco_high:
        return "medium"
    return "low"


def pack_confidence(model_confidence: float, sentences: list[DraftSentence]) -> float:
    """The model's self-report, capped by how much of the draft survived.

    A draft whose sentences were half withheld cannot be more than half
    trustworthy as a recommendation, whatever the model said about its own
    reasoning. Capping rather than averaging keeps the number honest in the
    direction that matters: it can only go down.
    """
    if not sentences:
        return 0.0
    kept = sum(1 for sentence in sentences if not sentence.withheld)
    kept_fraction = kept / len(sentences)
    return round(min(max(float(model_confidence), 0.0), 1.0, kept_fraction), 2)


# ── Database seams ────────────────────────────────────────────────────────
# Same pattern as triage.py: named module-level functions so tests can
# substitute them and the agent body reads as the decision sequence.
# load_case / load_message are imported from triage rather than reimplemented
# — one reader per canonical table, and the call pattern for compile() stays
# identical across the two agents by construction.

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def load_triage_result(triage_result_id: uuid.UUID) -> _TriageView:
    with Session(_get_engine()) as session:
        row = session.get(TriageResult, triage_result_id)
        if row is None:
            raise ResolveError(f"No itr360.triage_result row for {triage_result_id}.")
        return _TriageView(
            id=row.id,
            case_id=row.case_id,
            message_id=row.message_id,
            category=row.category,
            intent_class=row.intent_class,
            sub_category=row.sub_category,
            band=str(getattr(row.band, "value", row.band)),
            confidence=float(row.confidence) if row.confidence is not None else None,
        )


def next_version(case_id: uuid.UUID) -> int:
    """One past the highest ProposedAction version for this case.

    The task prompt said ``version=1``; this deviates deliberately. Task 20's
    ``_latest_proposed_action`` orders by ``version DESC, observed_at DESC``,
    so a second draft for the same case left at version 1 would rely entirely
    on the timestamp tiebreak to be found. Incrementing costs one cheap query
    and makes "latest" unambiguous.
    """
    with Session(_get_engine()) as session:
        highest = session.execute(
            select(func.max(ProposedAction.version)).where(ProposedAction.case_id == case_id)
        ).scalar()
    return int(highest or 0) + 1


def persist_proposed_action(**values: Any) -> ProposedAction:
    with Session(_get_engine()) as session:
        row = ProposedAction(**values)
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
    return row


# ── Prompt assembly ───────────────────────────────────────────────────────


def prompt_version() -> str:
    """Version declared by the template itself, so the two cannot drift."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    match = _PROMPT_VERSION_RE.search(text)
    return match.group(1) if match else PROMPT_PATH.stem


def _citation_id(citation: Any) -> str | None:
    chunk_id = getattr(citation, "chunk_id", None)
    return str(chunk_id) if chunk_id else None


def _render_citations(pack: Any) -> str:
    lines: list[str] = []
    for citation in getattr(pack, "citations", []) or []:
        chunk_id = _citation_id(citation)
        excerpt = getattr(citation, "excerpt", "") or ""
        parent = getattr(citation, "parent_text", None)
        lines.append(f'- chunk_id `{chunk_id}`: "{excerpt}"')
        if parent and parent != excerpt:
            lines.append(f"    surrounding context: {parent}")
    return "\n".join(lines) or "(no citations available)"


def build_messages(pack: Any, triage: _TriageView, case: Any, message: Any) -> list[dict]:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    rendered = (
        template.replace("{{CATEGORY}}", triage.category or "unknown")
        .replace("{{INTENT_CLASS}}", triage.intent_class or "unknown")
        .replace("{{SUB_CATEGORY}}", triage.sub_category or "—")
        .replace("{{CITATIONS}}", _render_citations(pack))
        .replace("{{SUBJECT}}", getattr(message, "subject", None) or getattr(case, "subject", "") or "")
        .replace("{{BODY}}", getattr(message, "body_redacted", "") or "")
    )
    return [{"role": "user", "content": rendered}]


# ── Sentence processing ───────────────────────────────────────────────────


def apply_rules(
    raw_sentences: list[dict[str, Any]], valid_chunk_ids: set[str]
) -> list[DraftSentence]:
    """Rule A then Rule B. Nothing is ever dropped — only marked withheld."""
    processed: list[DraftSentence] = []

    for raw in raw_sentences:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue

        # Rule A — keep only refs that exist in THIS pack. A sentence that
        # cites two chunks, one real and one hallucinated, keeps the real one.
        requested = raw.get("citation_refs") or []
        if isinstance(requested, str):
            requested = [requested]
        refs = [str(ref) for ref in requested if str(ref) in valid_chunk_ids]

        if not refs:
            processed.append(
                DraftSentence(
                    text=text,
                    citation_refs=[],
                    withheld=True,
                    withheld_reason="no citation in this context pack supports this sentence",
                )
            )
            continue

        # Rule B — overrides Rule A. A well-cited sentence claiming completed
        # work is exactly the failure this gate exists for.
        if claims_completed_action(text):
            processed.append(
                DraftSentence(
                    text=text,
                    citation_refs=refs,
                    withheld=True,
                    withheld_reason=(
                        "claims work already completed; nothing has been sent or "
                        "executed at this stage"
                    ),
                )
            )
            continue

        processed.append(DraftSentence(text=text, citation_refs=refs, withheld=False))

    return processed


def _evidence_dtos(pack: Any) -> list[dict[str, Any]]:
    """Citation DTOs for the NOT NULL ``evidence`` column.

    Guarded: Task 18's ``Citation.to_dto()`` calls ``source_ts.isoformat()``
    and ``source_ts`` is None when a chunk's message_id has no itr360.message
    row, which raises. Rather than let drafting die on an upstream edge case,
    that citation is emitted with access_status='missing' and logged. Flagged
    for a fix in compile.py, which is out of scope for this task.
    """
    dtos: list[dict[str, Any]] = []
    for citation in getattr(pack, "citations", []) or []:
        try:
            dtos.append(citation.to_dto())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resolve: citation %s could not be serialised to a DTO (%s) — "
                "emitting access_status='missing'.", _citation_id(citation), exc,
            )
            dtos.append(
                {
                    "source_system": getattr(citation, "source_system", "unknown"),
                    "source_type": getattr(citation, "source_type", "comment"),
                    "object_id": str(getattr(citation, "object_id", "") or ""),
                    "excerpt": "",
                    "source_ts": None,
                    "deep_link": "",
                    "access_status": "missing",
                }
            )
    return dtos


def _provenance(tenant_id: Any, run_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "source_system": SOURCE_SYSTEM,
        "external_id": None,
        "is_synthetic": False,
        "connector_run_id": run_id,
        "observed_at": now,
        "valid_from": now,
    }


def _audit(case_id: uuid.UUID, row: ProposedAction, withheld_count: int, low_context: bool) -> None:
    try:
        audit.write(
            actor="scout.agents.resolve",
            action="recommendation_generated",
            category="system",
            case_id=case_id,
            confidence=float(row.confidence) if row.confidence is not None else None,
            outputs={
                "proposed_action_id": str(row.id),
                "withheld_count": withheld_count,
                "confidence": float(row.confidence) if row.confidence is not None else None,
                "risk": row.risk,
                "low_context": low_context,
                "sentence_count": len(row.draft_sentences or []),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "resolve: could not write decision_audit row for case %s — %s: %s",
            case_id, type(exc).__name__, exc,
        )


# ── The agent ─────────────────────────────────────────────────────────────


async def recommend(case_id: uuid.UUID, triage_result_id: uuid.UUID) -> ProposedAction:
    """Draft a suggested reply for one triaged case.

    Always returns a persisted :class:`ProposedAction` with
    ``approval_required=True``. Never sends anything, never claims anything was
    done, and never cites evidence that is not in this call's ContextPack.
    """
    run_id = uuid.uuid4()
    now = datetime.now(UTC)

    triage = load_triage_result(triage_result_id)
    case = load_case(case_id)
    message = load_message(case_id, triage.message_id)

    acl_tags = [f"tenant:{case.tenant_id}"]
    if case.org_id:
        acl_tags.append(f"org:{case.org_id}")

    # Same call pattern triage.py uses — one retrieval per agent call.
    pack = compile_pack(
        intent=AGENT_NAME,
        case_id=case_id,
        query_text=f"{message.subject or case.subject}\n\n{message.body_redacted}",
        acl_tags=acl_tags,
    )

    version = prompt_version()
    evidence = _evidence_dtos(pack)

    # ── No evidence: do not draft. Flag for a human. ──────────────────────
    if getattr(pack, "low_context", False):
        placeholder = DraftSentence(
            text=NO_CONTEXT_TEXT,
            citation_refs=[],
            withheld=True,
            withheld_reason="context pack was empty (low_context=True); no model was called",
        )
        row = persist_proposed_action(
            id=uuid.uuid4(),
            case_id=case_id,
            triage_result_id=triage.id,
            resolution_path=None,
            recommended_action_text=NO_CONTEXT_TEXT,
            draft_sentences=[placeholder.to_json()],
            confidence=0.0,
            risk="high",  # no evidence means every claim would be unsupported
            recommended_owner=None,
            evidence=evidence,
            policy_ref=None,
            approval_required=True,
            model_name="none",
            prompt_version=version,
            version=next_version(case_id),
            version_token=str(uuid.uuid4()),
            status=INITIAL_STATUS,
            **_provenance(case.tenant_id, run_id, now),
        )
        _audit(case_id, row, withheld_count=1, low_context=True)
        return row

    # ── Draft ────────────────────────────────────────────────────────────
    result, meta = await reasoning.complete(
        agent=AGENT_NAME,
        prompt_version=version,
        messages=build_messages(pack, triage, case, message),
        schema=ResolutionOutput,
    )

    valid_chunk_ids = {
        cid for cid in (_citation_id(c) for c in getattr(pack, "citations", []) or []) if cid
    }
    sentences = apply_rules(result.sentences, valid_chunk_ids)

    kept = [sentence for sentence in sentences if not sentence.withheld]
    withheld_count = len(sentences) - len(kept)
    recommended_action_text = " ".join(s.text for s in kept).strip() or ALL_WITHHELD_TEXT
    confidence = pack_confidence(result.confidence, sentences)

    row = persist_proposed_action(
        id=uuid.uuid4(),
        case_id=case_id,
        triage_result_id=triage.id,
        resolution_path=result.resolution_path,
        recommended_action_text=recommended_action_text,
        draft_sentences=[sentence.to_json() for sentence in sentences],
        confidence=confidence,
        risk=risk_for(confidence),
        # itr360.problem_taxonomy has no owner/queue column (Task 10/11), and
        # no routing table exists in this schema — so there is nothing to look
        # up. Left None rather than invented; owner routing is a later slice.
        recommended_owner=None,
        evidence=evidence,
        # No policy engine exists in Slice 1. None rather than a placeholder id.
        policy_ref=None,
        # Slice 1's explicit non-goal: nothing is ever dispatched unreviewed.
        approval_required=True,
        model_name=meta.model,
        prompt_version=meta.prompt_version,
        version=next_version(case_id),
        # Fresh per row — Task 20's submit_decision checks this via if_match.
        version_token=str(uuid.uuid4()),
        status=INITIAL_STATUS,
        **_provenance(case.tenant_id, run_id, now),
    )

    _audit(case_id, row, withheld_count=withheld_count, low_context=False)
    return row


__all__ = [
    "AGENT_NAME",
    "DraftSentence",
    "ResolutionOutput",
    "ResolveError",
    "apply_rules",
    "claims_completed_action",
    "pack_confidence",
    "prompt_version",
    "recommend",
    "risk_for",
]
