"""
One-off remediation for the 8 itr360.kb_article rows that failed during
index_all_kb_articles() with a RedactionError.

These are real, varied LLM-generated article bodies (not a shared template
bug) — each failure is presumed to be its own coincidental PII-shaped
pattern in that particular article's generated text (e.g. a reference code
that happens to match a PAN/SSN/phone-like shape). There is deliberately no
attempt here to patch pii.py or to clean any one article's text in place —
this script's job is to document each failure, remove the 8 rows, and lean
on scripts/generate_kb_articles.py's existing idempotent top-up behaviour to
regenerate replacements, exactly the way a re-run of that script already
tops a class back up to its target count.

What this script does, in order
--------------------------------
1. DIAGNOSE (read-only): for each of the 8 ids, fetch title/body/category/
   problem_class from itr360.kb_article and run pii.redact() on the body
   directly, printing the specific RedactionError for the record. This step
   never modifies anything — it exists purely so there is a documented
   reason for each failure.
2. DELETE: remove exactly those 8 rows, by id only (never derived any other
   way). Each delete is confirmed to affect exactly 1 row; anything else
   (0 or >1) is reported clearly rather than swallowed, since it would mean
   this script's hardcoded id list is stale or wrong.
3. REGENERATE: for every (category, problem_class) pair that now has fewer
   than 15 articles as a result of the deletions, invoke
   scripts/generate_kb_articles.py's existing generation logic (prompt
   construction, cost-ceiling handling, and its idempotent
   (tenant, category, problem_class, title) skip-and-top-up persistence)
   so it tops each one back up to 15. Classes untouched by the deletions
   are never regenerated.

   NOTE on how the class is selected: every category in this taxonomy is
   itself a compound "domain/subdomain" string (e.g. "network/vpn",
   "licensing/activation" — confirmed live against itr360.problem_taxonomy
   below). generate_kb_articles.py's own --only flag parses its argument
   with `only.partition("/")` (first "/" only), which for a compound
   category like "network/vpn" splits into category="network",
   problem_class="vpn/vpn_connection_timeout" — matching nothing, for
   EVERY class in this taxonomy, not just the ones this script touches.
   That is a pre-existing limitation of --only's string parsing, not
   something in scope to fix here (scripts/generate_kb_articles.py is not
   modified by this script, on disk or otherwise). Rather than shell out to
   a CLI flag that cannot address a compound category, this script imports
   generate_kb_articles.py directly and calls its run() the same way the
   CLI would, but selects the target class by exact (category,
   problem_class) equality instead of routing through the lossy --only
   string — every other part of run() (prompt building, the cost ceiling,
   idempotent persistence) executes completely unchanged. Calling run()
   in-process for each affected class also means all regeneration in one
   invocation of this script shares a single cost-ceiling budget
   (settings.llm_cost_ceiling_usd_per_run), matching that ceiling's
   documented intent, rather than each class getting its own fresh budget
   as separate subprocesses would.
4. RE-INDEX: call scout.context.kb_index.index_all_kb_articles() again.
   Safe to re-run in full — point ids are deterministic uuid5s over
   (article id, chunk offsets), so this re-indexes everything without
   creating duplicate Qdrant points (see kb_index.py's own docstring).
   Reports how many of the newly-generated replacement articles indexed
   successfully this time, using the kb_indexed audit rows
   scout.context.kb_index writes per successfully-indexed article — no
   monkeypatching or modification of kb_index.py needed. Any brand-new
   failures (a different coincidental false positive on the regenerated
   content) are reported as a finding; this script does not loop or retry
   automatically.

Since none of the 8 original failures ever reached Qdrant (indexing raises
before any point is written for a failing article), there is nothing to
clean up on the Qdrant side for them.

Scope, deliberately narrow
---------------------------
Does not modify scout/governance/pii.py, scout/context/kb_index.py,
scout/context/embed.py, scout/context/chunk.py, or
scripts/generate_kb_articles.py — those are called into, unchanged.

Usage:
  poetry run python scripts/fix_failed_kb_articles.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from scout.canonical.models import KBArticle, ProblemTaxonomy
from scout.config import settings
from scout.context.kb_index import index_all_kb_articles
from scout.governance import audit
from scout.governance.pii import RedactionError, redact

TENANT_ID = uuid.UUID(str(settings.tenant_id))
TARGET_PER_CLASS = 15
GENERATE_SCRIPT = ROOT / "scripts" / "generate_kb_articles.py"

# The exact 8 ids that failed in the last index_all_kb_articles() run.
# Deliberately hardcoded: Step 2 deletes by this list only, never by
# re-deriving "which rows failed" from title/category/anything else.
FAILED_IDS: list[uuid.UUID] = [
    uuid.UUID("6915b062-09d0-4a00-bded-bf8857a3a054"),
    uuid.UUID("3633acb7-a789-4f53-8ae8-87a048e7ce66"),
    uuid.UUID("c9e4ac4f-21ba-4ee1-a73f-9800d0c8cc77"),
    uuid.UUID("5d1c951e-90a0-472f-b206-f95dc3942ee4"),
    uuid.UUID("3ce6e5ca-3107-436d-87c5-0b44b7c0cd14"),
    uuid.UUID("9d508ec6-78ad-488d-90c0-65e9b84555eb"),
    uuid.UUID("8e036811-fef2-48db-a3f8-24c031266020"),
    uuid.UUID("fb3b81bc-7b6d-4dd8-b8d2-091ba1ce33e8"),
]


def _print_header(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def _diagnose(session: Session) -> dict[uuid.UUID, KBArticle]:
    """STEP 1 — read-only. Fetch each failing row and reproduce its RedactionError."""
    _print_header("STEP 1 — diagnosing the 8 failed articles (read-only)")

    rows = session.execute(select(KBArticle).where(KBArticle.id.in_(FAILED_IDS))).scalars().all()
    by_id = {row.id: row for row in rows}

    for article_id in FAILED_IDS:
        article = by_id.get(article_id)
        if article is None:
            print(f"\n{article_id}: NOT FOUND in itr360.kb_article (already deleted, or id is wrong)")
            continue

        print(f"\n{article_id}")
        print(f"  category/problem_class: {article.category} / {article.problem_class}")
        print(f"  title: {article.title}")
        try:
            redact(article.body)
            print("  redact(body): unexpectedly PASSED this time — no RedactionError raised")
        except RedactionError as exc:
            print(f"  redact(body) FAILED: {exc}")

    return by_id


def _delete_failed(
    session: Session, by_id: dict[uuid.UUID, KBArticle]
) -> dict[uuid.UUID, tuple[str, str]]:
    """STEP 2 — delete the 8 rows by exact id, confirming each affects exactly 1 row."""
    _print_header("STEP 2 — deleting the 8 failed rows by id")

    class_by_id: dict[uuid.UUID, tuple[str, str]] = {}
    for article_id in FAILED_IDS:
        article = by_id.get(article_id)
        if article is not None:
            class_by_id[article_id] = (article.category, article.problem_class)

        result = session.execute(delete(KBArticle).where(KBArticle.id == article_id))
        if result.rowcount == 1:
            print(f"{article_id}: deleted (1 row)")
        else:
            print(
                f"{article_id}: WARNING — delete affected {result.rowcount} row(s), expected "
                "exactly 1. The hardcoded id list may be stale or wrong — investigate before "
                "trusting the regeneration step below."
            )
    session.commit()
    return class_by_id


def _affected_pairs_needing_regen(
    session: Session, class_by_id: dict[uuid.UUID, tuple[str, str]]
) -> list[tuple[str, str]]:
    """STEP 3a — which (category, problem_class) pairs now sit below the 15-article target."""
    _print_header("STEP 3 — checking which classes dropped below the 15-article target")

    pairs = sorted(set(class_by_id.values()))
    if not pairs:
        print("Could not determine category/problem_class for any of the 8 ids — nothing to regenerate.")
        return []

    needing_regen: list[tuple[str, str]] = []
    for category, problem_class in pairs:
        count = session.execute(
            select(func.count())
            .select_from(KBArticle)
            .where(
                KBArticle.tenant_id == TENANT_ID,
                KBArticle.category == category,
                KBArticle.problem_class == problem_class,
            )
        ).scalar_one()
        needs_regen = count < TARGET_PER_CLASS
        status = "below target — will regenerate" if needs_regen else "at/above target — skipping"
        print(f"{category} / {problem_class}: {count}/{TARGET_PER_CLASS} — {status}")
        if needs_regen:
            needing_regen.append((category, problem_class))

    return needing_regen


def _class_article_ids(session: Session, category: str, problem_class: str) -> set[uuid.UUID]:
    ids = session.execute(
        select(KBArticle.id).where(
            KBArticle.tenant_id == TENANT_ID,
            KBArticle.category == category,
            KBArticle.problem_class == problem_class,
        )
    ).scalars().all()
    return set(ids)


def _import_generate_kb_articles() -> types.ModuleType:
    """Load scripts/generate_kb_articles.py as a module, unmodified.

    scripts/ has no __init__.py, so it isn't import-able as a package —
    loaded via importlib instead of a subprocess so run() calls for every
    affected class in this script share one process (and one
    llm_cost_ceiling_usd_per_run budget, per the module docstring's intent).
    Importing only executes top-level definitions; main()/argparse never
    run because __name__ here is not "__main__".
    """
    spec = importlib.util.spec_from_file_location("_generate_kb_articles_impl", GENERATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register in sys.modules BEFORE exec: generate_kb_articles.py uses
    # `from __future__ import annotations`, so its pydantic models' field
    # types are resolved lazily from their __module__'s globals via
    # sys.modules — without this, KBArticleBatch's forward reference to
    # KBArticleDraft fails to resolve the first time reasoning.complete()
    # actually needs the schema (PydanticUserError: "not fully defined").
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _regenerate(session: Session, pairs: list[tuple[str, str]]) -> set[uuid.UUID]:
    """STEP 3b — top each affected class back up to 15 via generate_kb_articles.run().

    Calls run() exactly as the CLI would (same prompt construction, cost
    ceiling, and idempotent skip-existing/top-up persistence) for each
    affected class — see the module docstring above for why the class is
    selected by exact (category, problem_class) equality here instead of
    through --only's `partition("/")` parsing, which cannot address a
    compound category like "network/vpn" (every category in this
    taxonomy is compound, confirmed live below, not just the affected
    ones). Only _load_taxonomy — the class-selection step — is swapped
    out; generation and persistence run through the real, unmodified
    functions.
    """
    _print_header("STEP 3 (cont.) — regenerating replacements via generate_kb_articles.run()")

    if not pairs:
        print("No class was affected by the deletions — nothing to regenerate.")
        return set()

    session.commit()  # fresh transaction boundary before reading "before" snapshots
    before_ids = {pair: _class_article_ids(session, *pair) for pair in pairs}

    gen = _import_generate_kb_articles()
    original_load_taxonomy = gen._load_taxonomy

    for category, problem_class in pairs:
        label = f"{category}/{problem_class}"
        print(f"\n--- generate_kb_articles.run(per_class={TARGET_PER_CLASS}, only={label!r}) ---")

        def _exact_match_taxonomy(
            sess: Session, _only: str | None, _category: str = category, _problem_class: str = problem_class
        ) -> list[ProblemTaxonomy]:
            rows = sess.execute(
                select(ProblemTaxonomy).where(
                    ProblemTaxonomy.category == _category,
                    ProblemTaxonomy.problem_class == _problem_class,
                )
            ).scalars().all()
            return list(rows)

        gen._load_taxonomy = _exact_match_taxonomy
        try:
            exit_code = asyncio.run(gen.run(TARGET_PER_CLASS, label))
        finally:
            gen._load_taxonomy = original_load_taxonomy

        if exit_code != 0:
            print(f"WARNING: generate_kb_articles.run() returned {exit_code} for {label} — see output above.")

    session.commit()  # fresh transaction boundary before reading "after" snapshots
    new_ids: set[uuid.UUID] = set()
    for pair in pairs:
        after = _class_article_ids(session, *pair)
        new_ids |= after - before_ids[pair]

    print(f"\n{len(new_ids)} new replacement article(s) generated across {len(pairs)} class(es).")
    return new_ids


def _reindex_and_report(new_ids: set[uuid.UUID]) -> None:
    """STEP 4 — re-index everything; report indexing outcome for just the new ids."""
    _print_header("STEP 4 — re-indexing all kb_article rows (index_all_kb_articles)")

    totals = index_all_kb_articles()
    print(
        f"index_all_kb_articles(): articles={totals['articles']} indexed={totals['indexed']} "
        f"points={totals['points']} failed={totals['failed']}"
    )

    if not new_ids:
        print("\nNo newly-generated replacement articles to report indexing results for.")
        return

    # scout.context.kb_index writes one "kb_indexed" audit row per
    # successfully-indexed article (category="system"). Reading that trail
    # tells us which of the new ids made it through without needing to
    # touch or monkeypatch kb_index.py itself.
    system_rows = audit.list(category="system")
    indexed_ids = {
        row.outputs.get("kb_article_id")
        for row in system_rows
        if row.action == "kb_indexed" and row.outputs
    }

    new_id_strs = {str(article_id) for article_id in new_ids}
    succeeded = new_id_strs & indexed_ids
    failed = new_id_strs - indexed_ids

    print(
        f"\nOf {len(new_ids)} newly-generated replacement article(s): "
        f"{len(succeeded)} indexed successfully, {len(failed)} failed."
    )
    if failed:
        print(
            "\nNEW failures — a different coincidental false positive on the regenerated "
            "content. Reported as a finding, not retried automatically:"
        )
        for article_id in sorted(failed):
            print(f"  {article_id}")


def main() -> int:
    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as session:
        by_id = _diagnose(session)
        class_by_id = _delete_failed(session, by_id)
        pairs = _affected_pairs_needing_regen(session, class_by_id)
        new_ids = _regenerate(session, pairs)

    _reindex_and_report(new_ids)

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
