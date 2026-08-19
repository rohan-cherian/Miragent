"""
Task 19a (part 2) — the triage agent. MVP Phase 1's headline output.

In Phase 1 the system takes no action, so the classification *is* the
deliverable. That is why triage gets its own table, its own tier, its own
confidence gate and its own abstention path rather than being a field inside
the resolution engine.

The governing principle, from the spec: *"Below threshold the agent returns
needs_human_triage — it does not guess. A confident wrong answer costs more
than an honest abstention."*

What this module guarantees
---------------------------
* **A low-context pack never reaches a model.** ``compile()`` returning
  ``low_context=True`` short-circuits to ``needs_human_triage`` with zero LLM
  calls. That is an expected outcome (E7, the holiday-schedule email), not an
  error path.
* **At most two model calls per triage() call, ever.** Low confidence *or*
  unverifiable evidence spans trigger the single escalation retry at the next
  tier up; both are folded into one retry rather than compounding.
* **Off-taxonomy labels are a hard error.** Per the spec, a value outside
  ``itr360.problem_taxonomy`` "is a hard error, not a new label" — it raises
  :class:`TaxonomyViolationError` and is never persisted.
* **Priority is never the model's.** It is computed from the taxonomy default
  plus deterministic SLA rules; the prompt has no priority field at all.
* **Every model call is persisted.** One ``itr360.triage_result`` row per
  call, ``version`` incrementing — so a low-confidence case shows two rows,
  fast then standard, and the escalation is auditable.

Layering (Task 4): imports nothing from ``scout.gmail``, ``scout.connectors``
or ``googleapiclient``. Importing ``scout.canonical.models`` is expected.
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
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.agents import reasoning
from scout.canonical.models import Case, Message, ProblemTaxonomy, TriageResult
from scout.config import settings
from scout.context.compile import compile as compile_pack
from scout.governance import audit

logger = logging.getLogger(__name__)

AGENT_NAME = "triage"
PROMPT_PATH = Path(__file__).with_name("prompts") / "triage_v1.md"
_PROMPT_VERSION_RE = re.compile(r"<!--\s*prompt_version:\s*([^\s>]+)\s*-->")

# Provenance source_system for an agent-produced row. scout/canonical's own
# convention (decisions.py) is to name the originating system — "console" for
# a human action, "agent" for one of these.
SOURCE_SYSTEM = "agent"

# ── Deterministic priority rules ──────────────────────────────────────────
# The spec does not pin the SLA maths down, so the rule is stated here and
# kept simple and auditable:
#
#   1. Start from problem_taxonomy.default_priority for the matched
#      (category, problem_class). Unknown or absent -> "medium".
#   2. Escalate one rung if the case has been reopened at least once
#      (case_.reopened_count > 0) — a repeat is worse than a first contact.
#   3. Escalate one rung if the case is still open and older than
#      SLA_AGE_ESCALATION_HOURS.
#   4. Clamp at the top of the ladder.
#
# The model may explain the urgency in its rationale; it never produces this
# value. SLA_AGE_ESCALATION_HOURS is a local rule constant, not a pinned
# project-wide threshold — it is deliberately NOT read from settings, because
# settings.dup_window_hours (also 24) means something else entirely and
# reusing it would couple two unrelated rules.
PRIORITY_LADDER = ("low", "medium", "high", "critical")
DEFAULT_PRIORITY = "medium"
SLA_AGE_ESCALATION_HOURS = 24
_OPEN_STATUSES = frozenset({"new", "open", "pending", "in_progress"})


class TriageError(RuntimeError):
    """Base class for triage failures."""


class TaxonomyViolationError(TriageError):
    """The model returned a label outside itr360.problem_taxonomy."""


class TriageOutput(BaseModel):
    """Exactly what triage_v1.md instructs the model to return."""

    intent_class: str
    category: str
    sub_category: str | None = None
    sentiment: str | None = None
    confidence: float = 0.0
    rationale: str = ""
    urgency_signals: dict[str, Any] = Field(default_factory=dict)
    evidence_spans: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class _TaxonomyEntry:
    category: str
    problem_class: str
    description: str | None
    example_phrases: list[str]
    default_priority: str | None


@dataclass
class _CaseView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    org_id: uuid.UUID | None
    subject: str
    status: str
    opened_at: datetime
    reopened_count: int


@dataclass
class _MessageView:
    id: uuid.UUID
    case_id: uuid.UUID
    body_redacted: str
    subject: str | None


# ── Database seams ────────────────────────────────────────────────────────
# Kept as small module-level functions so tests can substitute them without a
# live database, and so triage() itself reads as the decision sequence.

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def load_taxonomy() -> list[_TaxonomyEntry]:
    """The classifier's whole label space (Task 11's seeded taxonomy)."""
    with Session(_get_engine()) as session:
        rows = session.execute(
            select(ProblemTaxonomy).order_by(
                ProblemTaxonomy.category, ProblemTaxonomy.problem_class
            )
        ).scalars().all()
    return [
        _TaxonomyEntry(
            category=row.category,
            problem_class=row.problem_class,
            description=row.description,
            example_phrases=list(row.example_phrases or []),
            default_priority=row.default_priority,
        )
        for row in rows
    ]


def load_case(case_id: uuid.UUID) -> _CaseView:
    with Session(_get_engine()) as session:
        row = session.get(Case, case_id)
        if row is None:
            raise TriageError(f"No itr360.case_ row for {case_id}.")
        return _CaseView(
            id=row.id,
            tenant_id=row.tenant_id,
            org_id=row.org_id,
            subject=row.subject,
            status=str(getattr(row.status, "value", row.status)),
            opened_at=row.opened_at,
            reopened_count=row.reopened_count or 0,
        )


def load_message(case_id: uuid.UUID, message_id: uuid.UUID | None) -> _MessageView:
    """The named message, or the case's first inbound message (the spec's default)."""
    with Session(_get_engine()) as session:
        if message_id is not None:
            row = session.get(Message, message_id)
        else:
            row = session.execute(
                select(Message)
                .where(Message.case_id == case_id, Message.direction == "inbound")
                .order_by(Message.sent_at.asc())
                .limit(1)
            ).scalars().first()

        if row is None:
            raise TriageError(
                f"No inbound itr360.message row for case {case_id}"
                + (f" / message {message_id}" if message_id else "")
            )
        return _MessageView(
            id=row.id,
            case_id=row.case_id,
            body_redacted=row.body_redacted or "",
            subject=row.subject,
        )


def persist_triage_result(**values: Any) -> TriageResult:
    """Insert one triage_result row and return it detached."""
    with Session(_get_engine()) as session:
        row = TriageResult(**values)
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


def _render_taxonomy(taxonomy: list[_TaxonomyEntry]) -> str:
    by_category: dict[str, list[_TaxonomyEntry]] = {}
    for entry in taxonomy:
        by_category.setdefault(entry.category, []).append(entry)

    lines: list[str] = []
    for category, entries in by_category.items():
        lines.append(f"- **{category}**")
        for entry in entries:
            suffix = f" — {entry.description}" if entry.description else ""
            lines.append(f"    - `{entry.problem_class}`{suffix}")
    return "\n".join(lines) or "(taxonomy is empty)"


def _render_exemplars(taxonomy: list[_TaxonomyEntry], per_class: int = 3) -> str:
    """Few-shot exemplars from problem_taxonomy.example_phrases (Task 11)."""
    lines: list[str] = []
    for entry in taxonomy:
        phrases = entry.example_phrases[:per_class]
        for phrase in phrases:
            lines.append(f'- "{phrase}" -> category `{entry.category}`, '
                         f"intent_class `{entry.problem_class}`")
    return "\n".join(lines) or "(no exemplars seeded)"


def _render_citations(pack: Any) -> str:
    lines: list[str] = []
    for index, citation in enumerate(getattr(pack, "citations", []) or [], start=1):
        excerpt = getattr(citation, "excerpt", "") or ""
        parent = getattr(citation, "parent_text", None)
        lines.append(f"[{index}] {excerpt}")
        if parent and parent != excerpt:
            lines.append(f"    context: {parent}")
    return "\n".join(lines) or "(no supporting context retrieved)"


def build_messages(
    pack: Any,
    case: _CaseView,
    message: _MessageView,
    taxonomy: list[_TaxonomyEntry],
) -> list[dict]:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    rendered = (
        template.replace("{{TAXONOMY}}", _render_taxonomy(taxonomy))
        .replace("{{EXEMPLARS}}", _render_exemplars(taxonomy))
        .replace("{{CITATIONS}}", _render_citations(pack))
        .replace("{{SUBJECT}}", message.subject or case.subject or "")
        .replace("{{BODY}}", message.body_redacted)
    )
    return [{"role": "user", "content": rendered}]


# ── Validation, banding, priority ─────────────────────────────────────────


def validate_against_taxonomy(result: TriageOutput, taxonomy: list[_TaxonomyEntry]) -> None:
    """Hard error on an off-taxonomy label — never a new label (spec, Task 19a).

    Raising rather than downgrading to needs_human_triage is deliberate: a
    label outside the taxonomy is a data-integrity problem, not a confidence
    problem, and silently banding it as "uncertain" would hide a broken prompt
    or a broken taxonomy seed behind a plausible-looking abstention.
    """
    if not taxonomy:
        raise TaxonomyViolationError(
            "itr360.problem_taxonomy is empty — run scripts/seed_taxonomy.py "
            "before triaging; classification has no label space."
        )

    categories = {entry.category for entry in taxonomy}
    if result.category not in categories:
        raise TaxonomyViolationError(
            f"Model returned category {result.category!r}, which is not in "
            f"problem_taxonomy ({len(categories)} categories). A value outside "
            "the taxonomy is a hard error, not a new label."
        )

    classes = {
        entry.problem_class for entry in taxonomy if entry.category == result.category
    }
    if result.intent_class not in classes:
        raise TaxonomyViolationError(
            f"Model returned intent_class {result.intent_class!r}, which is not a "
            f"problem_class of category {result.category!r}. A value outside the "
            "taxonomy is a hard error, not a new label."
        )


def verify_evidence_spans(result: TriageOutput, body: str) -> bool:
    """True when every span's offsets slice back to its own quoted text.

    This is the spec's own mechanism (the prompt asks for character offsets)
    rather than scanning the rationale for substrings — it is exact, and it is
    what Task 19b later relies on to refuse an uncitable claim. A result with
    no spans at all fails: the prompt requires at least one quote.
    """
    spans = result.evidence_spans or []
    if not spans:
        return False

    for span in spans:
        try:
            start = int(span["start"])
            end = int(span["end"])
            text = str(span["text"])
        except (KeyError, TypeError, ValueError):
            return False
        if start < 0 or end > len(body) or start >= end:
            return False
        if body[start:end] != text:
            return False
    return True


def band_for(confidence: float) -> str:
    """Confidence -> TriageBand, using only thresholds that already exist in config.

    needs_human_triage < triage_floor (0.60) <= low < triage_escalate (0.75)
    <= medium < reco_high (0.85) <= high

    The high boundary reuses settings.reco_high rather than introducing a new
    literal. That is the one judgement call here — flagged, since reco_high was
    written for recommendation confidence. Add a dedicated triage_high to
    config if the calibration run wants them to differ.
    """
    if confidence < settings.triage_floor:
        return "needs_human_triage"
    if confidence < settings.triage_escalate:
        return "low"
    if confidence < settings.reco_high:
        return "medium"
    return "high"


def _bump(priority: str, rungs: int) -> str:
    try:
        index = PRIORITY_LADDER.index(priority)
    except ValueError:
        index = PRIORITY_LADDER.index(DEFAULT_PRIORITY)
    return PRIORITY_LADDER[min(index + rungs, len(PRIORITY_LADDER) - 1)]


def compute_priority(
    taxonomy_default: str | None,
    case: _CaseView,
    now: datetime | None = None,
) -> str:
    """Deterministic priority. The model has no say in this value."""
    base = (taxonomy_default or DEFAULT_PRIORITY).strip().lower()
    if base not in PRIORITY_LADDER:
        base = DEFAULT_PRIORITY

    rungs = 0
    if case.reopened_count > 0:
        rungs += 1

    now = now or datetime.now(UTC)
    opened_at = case.opened_at
    if opened_at is not None:
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=UTC)
        age_hours = (now - opened_at).total_seconds() / 3600
        if case.status in _OPEN_STATUSES and age_hours > SLA_AGE_ESCALATION_HOURS:
            rungs += 1

    return _bump(base, rungs)


def _default_priority_for(
    taxonomy: list[_TaxonomyEntry], category: str | None, problem_class: str | None
) -> str | None:
    for entry in taxonomy:
        if entry.category == category and entry.problem_class == problem_class:
            return entry.default_priority
    return None


# ── The agent ─────────────────────────────────────────────────────────────


def _provenance(case: _CaseView, run_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    return {
        "tenant_id": case.tenant_id,
        "source_system": SOURCE_SYSTEM,
        "external_id": None,
        "is_synthetic": False,
        "connector_run_id": run_id,
        "observed_at": now,
        "valid_from": now,
    }


async def triage(case_id: uuid.UUID, message_id: uuid.UUID | None = None) -> TriageResult:
    """Classify one case. Returns the final persisted ``TriageResult`` row.

    ``message_id`` defaults to the case's first inbound message, which is what
    the spec's ``triage(case_id)`` means; passing one explicitly is an override.
    """
    run_id = uuid.uuid4()
    now = datetime.now(UTC)

    case = load_case(case_id)
    message = load_message(case_id, message_id)
    acl_tags = [f"tenant:{case.tenant_id}"]
    if case.org_id:
        acl_tags.append(f"org:{case.org_id}")

    # One retrieval per triage() call — compile() itself calls retrieve() once.
    pack = compile_pack(
        intent=AGENT_NAME,
        case_id=case_id,
        query_text=f"{message.subject or case.subject}\n\n{message.body_redacted}",
        acl_tags=acl_tags,
    )

    # ── Abstention path: no model call at all ─────────────────────────────
    if getattr(pack, "low_context", False):
        row = persist_triage_result(
            id=uuid.uuid4(),
            case_id=case_id,
            message_id=message.id,
            intent_class=None,
            category=None,
            sub_category=None,
            priority=compute_priority(None, case, now),
            urgency_signals=None,
            sentiment=None,
            confidence=0.0,
            band="needs_human_triage",
            rationale=(
                "Context pack was empty (low_context=True) — no evidence cleared "
                "the retrieval floor and the ACL gate, so no model was called. "
                "Routed to a human rather than guessing."
            ),
            evidence_spans=None,
            model_name="none",
            prompt_version=prompt_version(),
            tier_used="none",
            latency_ms=None,
            tokens_in=None,
            tokens_out=None,
            cost_usd=None,
            version=1,
            **_provenance(case, run_id, now),
        )
        _audit(case_id, row, attempts=0, low_context=True)
        return row

    taxonomy = load_taxonomy()
    messages = build_messages(pack, case, message, taxonomy)
    version = prompt_version()

    # ── At most two model calls. Low confidence and unverifiable evidence
    #    spans both feed the same single escalation, never two retries. ────
    tier: str | None = None
    attempt = 0
    rows: list[TriageResult] = []
    result: TriageOutput | None = None
    meta: reasoning.CallMeta | None = None
    spans_ok = False

    while attempt < 2:
        attempt += 1
        result, meta = await reasoning.complete(
            agent=AGENT_NAME,
            prompt_version=version,
            messages=messages,
            schema=TriageOutput,
            tier=tier,
        )
        validate_against_taxonomy(result, taxonomy)
        spans_ok = verify_evidence_spans(result, message.body_redacted)

        rows.append(
            persist_triage_result(
                id=uuid.uuid4(),
                case_id=case_id,
                message_id=message.id,
                intent_class=result.intent_class,
                category=result.category,
                sub_category=result.sub_category,
                priority=compute_priority(
                    _default_priority_for(taxonomy, result.category, result.intent_class),
                    case,
                    now,
                ),
                urgency_signals=result.urgency_signals or None,
                sentiment=result.sentiment,
                confidence=float(result.confidence),
                band=_final_band(result.confidence, spans_ok, attempt),
                rationale=result.rationale,
                evidence_spans={"spans": result.evidence_spans} if result.evidence_spans else None,
                model_name=meta.model,
                prompt_version=meta.prompt_version,
                tier_used=meta.tier,
                latency_ms=meta.latency_ms,
                tokens_in=meta.tokens_in,
                tokens_out=meta.tokens_out,
                cost_usd=meta.cost_usd,
                version=attempt,
                **_provenance(case, run_id, now),
            )
        )

        escalate = result.confidence < settings.triage_escalate or not spans_ok
        if not escalate:
            break

        next_up = reasoning.next_tier_up(meta.tier)
        if next_up is None:
            logger.warning(
                "triage: %s already at the top tier (%s) — no escalation available.",
                case_id, meta.tier,
            )
            break
        tier = next_up

    final = rows[-1]
    _audit(case_id, final, attempts=len(rows), low_context=False)
    return final


def _final_band(confidence: float, spans_ok: bool, attempt: int) -> str:
    """Band for a persisted attempt.

    Unverifiable evidence spans force needs_human_triage on the *final*
    attempt: a classification we cannot trace back to the email is exactly the
    confident-but-unsupported answer this gate exists to refuse. On the first
    attempt the raw band is recorded as-is so the escalation stays auditable.
    """
    band = band_for(confidence)
    if attempt >= 2 and not spans_ok:
        return "needs_human_triage"
    return band


def _audit(case_id: uuid.UUID, row: TriageResult, attempts: int, low_context: bool) -> None:
    """One audit row per triage() call — both attempts summarised in one outcome."""
    try:
        audit.write(
            actor="scout.agents.triage",
            action="triage",
            category="system",
            case_id=case_id,
            confidence=float(row.confidence) if row.confidence is not None else None,
            outputs={
                "band": str(getattr(row.band, "value", row.band)),
                "confidence": float(row.confidence) if row.confidence is not None else None,
                "category": row.category,
                "intent_class": row.intent_class,
                "priority": row.priority,
                "attempts": attempts,
                "low_context": low_context,
                "tier_used": row.tier_used,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "triage: could not write decision_audit row for case %s — %s: %s",
            case_id, type(exc).__name__, exc,
        )


__all__ = [
    "AGENT_NAME",
    "TaxonomyViolationError",
    "TriageError",
    "TriageOutput",
    "band_for",
    "compute_priority",
    "prompt_version",
    "triage",
    "validate_against_taxonomy",
    "verify_evidence_spans",
]
