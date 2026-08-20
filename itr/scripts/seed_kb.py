"""
Task 0, Part 4 — seed the 25 hand-written KB articles from data/kb_articles/.

This is deliberately a THIN WRAPPER over the existing pipeline, not a
standalone indexer. A naive script that chunks/embeds the markdown files
itself and writes its own payload keys would produce Qdrant points that
index fine and then never surface: scout/context/compile.py and
scout/context/retrieve.py branch on payload["source_system"] == "kb_article"
and payload["kb_article_id"], and those are only set correctly by
scout.context.kb_index.index_kb_article(). So this script does exactly two
things: (1) upsert an itr360.kb_article row per markdown file via the
existing KBArticle model, and (2) call index_kb_article() on it. No
chunking or embedding logic lives here.

Load order: taxonomy, then KB, always. Every article's problem_class is a
composite FK into itr360.problem_taxonomy(category, problem_class) — if
scripts/seed_taxonomy.py hasn't been run (or was run against the fallback
vocabulary rather than data/taxonomy.json), the insert fails with an
IntegrityError, which is caught here and reported with the offending file
and a pointer back to seed_taxonomy.py rather than a raw traceback.

Idempotency: matched on (tenant_id, external_id), where external_id carries
the front-matter kb_id ("KB-CFG-09") — the Provenance.external_id column
exists for exactly this. Re-running updates the existing row and re-indexes
it (index_kb_article()'s point ids are deterministic uuid5, so Qdrant
upsert overwrites rather than duplicates).

Cost note: every run re-embeds every article's chunks via
index_kb_article() -> embed_chunks() (there is no "already indexed" marker
to skip on, see kb_index.py's own docstring). For ~25 articles at a few
chunks each this is on the order of cents, not dollars, but it is a real
OpenAI embeddings call every time this script runs.

Usage:
  poetry run python scripts/seed_kb.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scout.canonical.models import KBArticle
from scout.config import settings
from scout.context.kb_index import index_kb_article

KB_ARTICLES_DIR = ROOT / "data" / "kb_articles"
SOURCE = "hand_written"
SOURCE_SYSTEM = "kb_article"

TENANT_ID = uuid.UUID(str(settings.tenant_id))


class ArticleParseError(Exception):
    pass


def _parse_article(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ArticleParseError(f"{path.name}: missing front-matter block (must start with '---')")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ArticleParseError(f"{path.name}: malformed front-matter — expected two '---' delimiters")

    front_matter_raw, body = parts[1], parts[2].strip()
    front_matter = yaml.safe_load(front_matter_raw) or {}

    required = ("kb_id", "title", "problem_class", "category")
    missing = [key for key in required if not front_matter.get(key)]
    if missing:
        raise ArticleParseError(f"{path.name}: front-matter missing required field(s): {missing}")

    if not body:
        raise ArticleParseError(f"{path.name}: empty body")

    return {
        "kb_id": str(front_matter["kb_id"]).strip(),
        "title": str(front_matter["title"]).strip(),
        "problem_class": str(front_matter["problem_class"]).strip(),
        "category": str(front_matter["category"]).strip(),
        "body": body,
    }


def _upsert_article(session: Session, parsed: dict, run_id: uuid.UUID) -> tuple[KBArticle, bool]:
    """Upsert on (tenant_id, external_id). Returns (article, inserted)."""
    row = session.execute(
        select(KBArticle).where(
            KBArticle.tenant_id == TENANT_ID,
            KBArticle.external_id == parsed["kb_id"],
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    inserted = row is None

    if row is None:
        row = KBArticle(
            id=uuid.uuid4(),
            category=parsed["category"],
            problem_class=parsed["problem_class"],
            title=parsed["title"],
            body=parsed["body"],
            source=SOURCE,
            model_name=None,
            tenant_id=TENANT_ID,
            source_system=SOURCE_SYSTEM,
            external_id=parsed["kb_id"],
            is_synthetic=False,
            connector_run_id=run_id,
            observed_at=now,
            valid_from=now,
        )
        session.add(row)
    else:
        row.category = parsed["category"]
        row.problem_class = parsed["problem_class"]
        row.title = parsed["title"]
        row.body = parsed["body"]
        row.source = SOURCE
        row.connector_run_id = run_id
        row.observed_at = now

    session.flush()
    return row, inserted


def main() -> int:
    if not KB_ARTICLES_DIR.exists():
        print(f"No {KB_ARTICLES_DIR.relative_to(ROOT)} directory found — nothing to seed.")
        return 1

    paths = sorted(KB_ARTICLES_DIR.glob("*.md"))
    if not paths:
        print(f"No .md files found under {KB_ARTICLES_DIR.relative_to(ROOT)}.")
        return 1

    run_id = uuid.uuid4()
    engine = create_engine(settings.database_url, future=True)
    totals = {"loaded": 0, "updated": 0, "points": 0, "failed": 0}

    with Session(engine) as session:
        for path in paths:
            try:
                parsed = _parse_article(path)
            except ArticleParseError as exc:
                totals["failed"] += 1
                print(f"{path.name}: SKIPPED — {exc}")
                continue

            try:
                article, inserted = _upsert_article(session, parsed, run_id)
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                totals["failed"] += 1
                print(
                    f"{path.name}: FAILED — problem_class "
                    f"'{parsed['category']}/{parsed['problem_class']}' is not in "
                    f"itr360.problem_taxonomy ({type(exc).__name__}). "
                    "Run `poetry run python scripts/seed_taxonomy.py` first — "
                    "taxonomy must load before KB articles."
                )
                continue

            try:
                points = index_kb_article(article)
            except Exception as exc:  # noqa: BLE001 — reported, not fatal; re-run retries
                totals["failed"] += 1
                print(f"{path.name}: row saved but indexing FAILED ({type(exc).__name__}: {exc})")
                continue

            totals["points"] += points
            if inserted:
                totals["loaded"] += 1
                print(f"{path.name}: loaded ({parsed['kb_id']}) — {points} point(s)")
            else:
                totals["updated"] += 1
                print(f"{path.name}: updated ({parsed['kb_id']}) — {points} point(s)")

    print()
    print(
        f"done — loaded={totals['loaded']} updated={totals['updated']} "
        f"points={totals['points']} failed={totals['failed']}"
    )
    return 0 if totals["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
