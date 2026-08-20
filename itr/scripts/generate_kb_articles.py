"""
Generate Knowledge Base solution articles — 15 per problem class.

For EVERY row in itr360.problem_taxonomy (read live — never hardcoded, so
this works against whatever is seeded now or later), make ONE
reasoning.complete() call that returns a pydantic-validated list of 15
distinct articles, and persist each as an itr360.kb_article row.

Cost model — deliberately bounded
---------------------------------
One call per CLASS, not per article: 17 classes today -> 17 calls, not
255. This is the only generation strategy. There is no per-article retry
fallback, on purpose: a fallback that silently multiplies calls 15x is how
a $5 ceiling becomes a $75 surprise. If a class's response fails
validation it is reported and skipped; re-run the script to retry it.

reasoning.complete() is called with an EXPLICIT tier="standard". There is
no "kb_generation" entry in settings.agent_tier, and complete()'s tier
override bypasses that lookup (reasoning.resolve_tier), so no config.py
change is needed. Cost still meters under settings.llm_cost_ceiling_usd_per_run;
when the ceiling is reached, complete() raises CostCeilingExceededError
BEFORE dispatching and this script stops cleanly with a summary.

Redaction
---------
No pii.redact() pass on the FINAL LLM-generated article bodies. The
content is LLM-generated, synthetic solution text produced from a
taxonomy label — it contains no real person's data by construction, and
the prompt explicitly forbids invented-but-realistic personal details.
(The indexing step still runs embed_chunks()'s own redact() pass before
anything enters Qdrant — see scout/context/kb_index.py — so even this
assumption is not load-bearing for governance.)

HOWEVER — the INPUT fragments assembled into the outgoing prompt (the
taxonomy's description/example_phrases, and titles from previous runs
echoed back to the model) are NOT guaranteed PII-free: example_phrases
were seeded from a workbook/fallback and could contain a stray realistic-
looking value, and a previous run's LLM-generated titles could coincide
with a name-shaped token. Every fragment is therefore pre-redacted
individually before being formatted into the prompt (see
_safe_fragment()), and the fully-assembled prompt is redacted once more
as a pre-flight check immediately before dispatch (see
_generate_for_class()) — this pre-flight call is deterministic, so a pass
here guarantees the in-flight redact() pass inside reasoning.complete()
will also pass, and any failure is reported with the class name attached
rather than as an opaque error.

Idempotency
-----------
Existing (tenant, category, problem_class, title) rows are skipped, and the
model is told which titles already exist so it produces new ones. Re-running
tops each class up to the target rather than duplicating it.

Diagnosing a redaction failure
-------------------------------
If a class fails with a RedactionError, re-run with --diagnose-redaction:
this makes NO LLM calls and writes NOTHING to the database. It rebuilds
every class's exact prompt, runs pii.redact() on each one, and for any
that fail, bisects the prompt line-by-line (using only the public
redact() function — scout/governance/pii.py itself is never touched) to
report the smallest surviving fragment that still reproduces the
failure, so the offending text can be found directly instead of guessed
at.

Usage:
  poetry run python scripts/generate_kb_articles.py [--per-class 15] [--only CATEGORY/CLASS]
  poetry run python scripts/generate_kb_articles.py --diagnose-redaction
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scout.agents import reasoning
from scout.agents.reasoning import CostCeilingExceededError
from scout.canonical.models import KBArticle, ProblemTaxonomy
from scout.config import settings
from scout.governance.pii import RedactionError, redact

AGENT_NAME = "kb_generation"
TIER = "standard"  # explicit — bypasses settings.agent_tier, see module docstring
PROMPT_VERSION = "kb_generation_v1"
SOURCE_SYSTEM = "kb_article"
DEFAULT_PER_CLASS = 15

TENANT_ID = uuid.UUID(str(settings.tenant_id))


class KBArticleDraft(BaseModel):
    title: str
    body: str


class KBArticleBatch(BaseModel):
    """What the model returns: one batch of articles for one problem class."""

    articles: list[KBArticleDraft] = Field(default_factory=list)


PROMPT = """\
You write internal IT-support knowledge base articles.

Produce exactly {count} DISTINCT solution articles for this problem class:

  category:      {category}
  problem_class: {problem_class}
  description:   {description}
  example customer phrasings: {phrases}

Each article must have:
- "title": a specific, searchable title (8-14 words) naming the concrete symptom or cause
- "body": 180-320 words in plain prose with short numbered steps, covering
    1. the problem as a support agent would recognise it (specific symptom / error text / trigger)
    2. the likely cause
    3. step-by-step resolution an agent can follow
    4. one or two notes (when to escalate, what to check first, what NOT to do)

VARIATION IS THE POINT. Across the {count} articles vary the specific symptom, the root
cause, the platform or client involved, and the exact steps — no two should read as
near-duplicates. Examples of axes to vary: first-time vs recurring, one user vs many,
after an upgrade / renewal / password change, desktop vs mobile vs browser, network
vs account vs licence cause.

Rules:
- Do NOT include any real or realistic personal data: no names, email addresses, phone
  numbers, account numbers, card numbers, addresses. Refer to "the user", "the account",
  "the licence key" generically.
- Do NOT reuse any of these titles that already exist: {existing_titles}
- Output must be exactly one JSON object with an "articles" array containing {count} entries, formatted as:
{{"articles": [{{"title": "<article title>", "body": "<article body>"}}]}}
"""


def _safe_fragment(text: str, label: str) -> str:
    """Redact one input fragment before it's formatted into the outgoing prompt.

    Fragments come from the taxonomy (description/example_phrases) or from
    a previous run's generated titles — neither is guaranteed PII-free.
    Pre-redacting each one individually means a value can never appear
    once-masked-once-surviving in the final assembled prompt, which is
    what previously tripped pii.py's post-redaction consistency check.
    """
    if not text:
        return text
    try:
        result = redact(text)
        return result.text
    except RedactionError as exc:
        raise RedactionError(f"failed pre-redacting {label}: {exc}") from exc


def _build_prompt(entry: ProblemTaxonomy, count: int, existing: set[str]) -> str:
    description = _safe_fragment(entry.description or "(no description)", "description")
    phrases_raw = "; ".join(entry.example_phrases or []) or "(none)"
    phrases = _safe_fragment(phrases_raw, "example_phrases")
    titles_raw = "; ".join(sorted(existing)) or "(none yet)"
    existing_titles = _safe_fragment(titles_raw, "existing_titles")

    return PROMPT.format(
        count=count,
        category=entry.category,
        problem_class=entry.problem_class,
        description=description,
        phrases=phrases,
        existing_titles=existing_titles,
    )


def _preflight_check(prompt: str, label: str) -> None:
    """Redact the fully-assembled prompt once before dispatch.

    redact() is deterministic, so a pass here guarantees the identical
    in-flight redact() call inside reasoning.complete() will also pass.
    A failure here is reported with the class label attached, instead of
    surfacing later as an opaque error with no attribution.
    """
    try:
        redact(prompt)
    except RedactionError as exc:
        raise RedactionError(f"[{label}] pre-flight redaction failed: {exc}") from exc


def _load_taxonomy(session: Session, only: str | None) -> list[ProblemTaxonomy]:
    rows = session.execute(
        select(ProblemTaxonomy).order_by(ProblemTaxonomy.category, ProblemTaxonomy.problem_class)
    ).scalars().all()
    if only:
        category, _, problem_class = only.partition("/")
        rows = [r for r in rows if r.category == category and r.problem_class == problem_class]
    return list(rows)


def _existing_titles(session: Session, category: str, problem_class: str) -> set[str]:
    rows = session.execute(
        select(KBArticle.title).where(
            KBArticle.tenant_id == TENANT_ID,
            KBArticle.category == category,
            KBArticle.problem_class == problem_class,
        )
    ).scalars().all()
    return {title.strip().lower() for title in rows}


async def _generate_for_class(
    entry: ProblemTaxonomy, count: int, existing: set[str]
) -> tuple[KBArticleBatch, reasoning.CallMeta]:
    label = f"{entry.category} / {entry.problem_class}"
    prompt = _build_prompt(entry, count, existing)
    _preflight_check(prompt, label)
    return await reasoning.complete(
        agent=AGENT_NAME,
        prompt_version=PROMPT_VERSION,
        messages=[{"role": "user", "content": prompt}],
        schema=KBArticleBatch,
        tier=TIER,
    )


def _persist(
    session: Session,
    entry: ProblemTaxonomy,
    batch: KBArticleBatch,
    model_name: str,
    existing: set[str],
    run_id: uuid.UUID,
    cap: int,
) -> int:
    now = datetime.now(UTC)
    inserted = 0
    seen_this_batch: set[str] = set()

    for draft in batch.articles:
        title = draft.title.strip()
        body = draft.body.strip()
        key = title.lower()
        if not title or not body or key in existing or key in seen_this_batch:
            continue
        if inserted >= cap:
            break
        session.add(
            KBArticle(
                id=uuid.uuid4(),
                category=entry.category,
                problem_class=entry.problem_class,
                title=title,
                body=body,
                source="llm_generated",
                model_name=model_name,
                tenant_id=TENANT_ID,
                source_system=SOURCE_SYSTEM,
                external_id=None,
                is_synthetic=True,  # synthetic content, flagged as such in provenance
                connector_run_id=run_id,
                observed_at=now,
                valid_from=now,
            )
        )
        seen_this_batch.add(key)
        inserted += 1

    session.commit()
    return inserted


async def run(per_class: int, only: str | None) -> int:
    run_id = uuid.uuid4()
    engine = create_engine(settings.database_url, future=True)
    totals = {"classes": 0, "generated": 0, "skipped_full": 0, "failed": 0}

    with Session(engine) as session:
        taxonomy = _load_taxonomy(session, only)
        if not taxonomy:
            print("No problem_taxonomy rows found — run scripts/seed_taxonomy.py first.")
            return 1

        print(f"kb_generation run {run_id}: {len(taxonomy)} class(es), target {per_class} each, "
              f"tier={TIER}, ceiling=${settings.llm_cost_ceiling_usd_per_run:.2f}")

        for entry in taxonomy:
            label = f"{entry.category} / {entry.problem_class}"
            totals["classes"] += 1
            existing = _existing_titles(session, entry.category, entry.problem_class)
            need = per_class - len(existing)
            if need <= 0:
                totals["skipped_full"] += 1
                print(f"{label}: {len(existing)}/{per_class} already present — skipping")
                continue

            try:
                batch, meta = await _generate_for_class(entry, need, existing)
            except CostCeilingExceededError as exc:
                print(f"\nSTOPPED — {exc}")
                break
            except Exception as exc:  # noqa: BLE001 — reported, not fatal; re-run retries
                totals["failed"] += 1
                print(f"{label}: generation FAILED ({type(exc).__name__}: {exc}) — skipped, re-run to retry")
                continue

            inserted = _persist(session, entry, batch, meta.model, existing, run_id, cap=need)
            totals["generated"] += inserted
            spend = reasoning.run_cost()["total_usd"]
            print(f"{label}: {len(existing) + inserted}/{per_class} generated "
                  f"(+{inserted}, {meta.tokens_out or 0} tokens out, ${meta.cost_usd or 0:.4f}, "
                  f"run total ${spend:.4f})")

    print()
    print(f"done — classes={totals['classes']} generated={totals['generated']} "
          f"already_full={totals['skipped_full']} failed={totals['failed']} "
          f"spend=${reasoning.run_cost()['total_usd']:.4f}")
    return 0 if totals["failed"] == 0 else 1


def _bisect_minimal_failure(text: str) -> str | None:
    """Shrink `text` to the smallest line-range that still raises RedactionError.

    Best-effort binary search over lines (not characters) — good enough to
    point a human at the right paragraph/sentence without needing to touch
    pii.py itself. Returns None if the full text doesn't actually fail
    (nothing to bisect).
    """

    def fails(candidate: str) -> bool:
        if not candidate.strip():
            return False
        try:
            redact(candidate)
            return False
        except RedactionError:
            return True
        except Exception:
            return False

    if not fails(text):
        return None

    lines = text.split("\n")
    changed = True
    while changed and len(lines) > 1:
        changed = False
        mid = len(lines) // 2
        first_half = lines[:mid]
        second_half = lines[mid:]
        if fails("\n".join(second_half)):
            lines = second_half
            changed = True
        elif fails("\n".join(first_half)):
            lines = first_half
            changed = True
        else:
            # failure depends on both halves together — try trimming one
            # line at a time from each end instead of a further binary split
            trimmed = True
            while trimmed and len(lines) > 1:
                trimmed = False
                if fails("\n".join(lines[1:])):
                    lines = lines[1:]
                    trimmed = True
                    changed = True
                elif fails("\n".join(lines[:-1])):
                    lines = lines[:-1]
                    trimmed = True
                    changed = True
            break

    return "\n".join(lines)


def diagnose_redaction(per_class: int, only: str | None) -> int:
    """No LLM calls, no database writes. Finds which classes' assembled
    prompts fail redact(), and for each, the minimal reproducing fragment.
    """
    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as session:
        taxonomy = _load_taxonomy(session, only)
        if not taxonomy:
            print("No problem_taxonomy rows found — run scripts/seed_taxonomy.py first.")
            return 1

        print(f"diagnose-redaction: checking {len(taxonomy)} class(es), no LLM calls, no writes\n")
        any_failed = False

        for entry in taxonomy:
            label = f"{entry.category} / {entry.problem_class}"
            existing = _existing_titles(session, entry.category, entry.problem_class)
            need = max(per_class - len(existing), 1)
            prompt = _build_prompt(entry, need, existing)  # fragments already pre-redacted here

            try:
                redact(prompt)
                print(f"{label}: OK")
            except RedactionError as exc:
                any_failed = True
                print(f"{label}: FAILS pre-flight redaction ({exc})")
                minimal = _bisect_minimal_failure(prompt)
                if minimal:
                    print("  minimal reproducing fragment:")
                    print("  " + "-" * 60)
                    for line in minimal.splitlines():
                        print(f"  | {line}")
                    print("  " + "-" * 60)
                else:
                    print("  could not isolate a smaller reproducing fragment")
                print()

        if not any_failed:
            print("\nAll class prompts pass pii.redact() cleanly.")
        return 1 if any_failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate KB articles per problem class.")
    parser.add_argument("--per-class", type=int, default=DEFAULT_PER_CLASS)
    parser.add_argument("--only", help="Restrict to one CATEGORY/PROBLEM_CLASS")
    parser.add_argument(
        "--diagnose-redaction",
        action="store_true",
        help="No LLM calls, no writes: find which class prompts fail redact() and why.",
    )
    args = parser.parse_args()

    if args.diagnose_redaction:
        return diagnose_redaction(args.per_class, args.only)

    return asyncio.run(run(args.per_class, args.only))


if __name__ == "__main__":
    raise SystemExit(main())