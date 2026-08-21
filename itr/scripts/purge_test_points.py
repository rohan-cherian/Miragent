"""
One-off cleanup — purge test-written points from the shared dev Qdrant
collection (settings.qdrant_collection_name).

Background: several live tests (tests/context/test_kb_index.py,
tests/context/test_pack.py, tests/context/test_index.py, and — until this
fix — tests/test_seed_kb.py) wrote directly into the shared dev collection
rather than an isolated one. Because they used the placeholder tenant's real
acl_tags, those points are retrievable by genuine /context-pack calls —
test garbage can surface as citations. tests/test_seed_kb.py's live test now
isolates itself into a disposable collection (see its
_isolated_qdrant_collection fixture) so this class of pollution cannot
recur from that file going forward; the other live test files above still
write into the shared collection and are out of scope for this change (see
the accompanying report — fixing them is a separate task).

Identification, not pattern-matching
-------------------------------------
A test point is identified by checking whether its declared identity
actually exists in Postgres, not by guessing at fixture content:

  * KB-shaped point (payload["source_system"] == "kb_article"): orphaned
    if payload["kb_article_id"] does not match a live itr360.kb_article
    row. Every REAL KB article is persisted to Postgres first (via
    scripts/seed_kb.py or scripts/generate_kb_articles.py) and only then
    indexed — a KB point with no backing row was indexed by a test that
    never persisted its (throwaway) KBArticle to the database at all.

  * Everything else (message-chunk-shaped, i.e. email chunks written via
    scout.context.embed.upsert_chunks): orphaned if payload["message_id"]
    is missing, malformed, or does not match a live itr360.message row.
    Every REAL email chunk is indexed from a persisted itr360.message row
    (scripts/ingest_canonical.py) — this is the same principle as above.

This can never delete a genuine production point: a real point always has
a backing Postgres row by construction of how it got indexed in the first
place.

Usage:
  poetry run python scripts/purge_test_points.py            # dry run (default)
  poetry run python scripts/purge_test_points.py --apply    # actually delete
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient, models
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scout.canonical.models import KBArticle, Message
from scout.config import settings

KB_SOURCE_SYSTEM = "kb_article"


def _load_real_ids() -> tuple[set[str], set[str]]:
    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as session:
        kb_ids = {str(row) for row in session.execute(select(KBArticle.id)).scalars().all()}
        message_ids = {str(row) for row in session.execute(select(Message.id)).scalars().all()}
    return kb_ids, message_ids


def _is_orphaned(payload: dict, real_kb_ids: set[str], real_message_ids: set[str]) -> str | None:
    """Returns a reason string if orphaned, else None."""
    if (payload.get("source_system") or None) == KB_SOURCE_SYSTEM:
        kb_article_id = payload.get("kb_article_id")
        if not kb_article_id or str(kb_article_id) not in real_kb_ids:
            return f"kb_article_id {kb_article_id!r} has no itr360.kb_article row"
        return None

    message_id = payload.get("message_id")
    if not message_id:
        return "no message_id in payload"
    try:
        uuid.UUID(str(message_id))
    except (ValueError, TypeError):
        return f"message_id {message_id!r} is not a valid uuid"
    if str(message_id) not in real_message_ids:
        return f"message_id {message_id!r} has no itr360.message row"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry run)")
    args = parser.parse_args()

    client = QdrantClient(url=settings.qdrant_url)
    collection = settings.qdrant_collection_name
    if not client.collection_exists(collection):
        print(f"collection {collection!r} does not exist — nothing to do")
        return 0

    before = client.get_collection(collection).points_count
    print(f"collection: {collection!r} — {before} point(s) before")

    real_kb_ids, real_message_ids = _load_real_ids()
    print(f"Postgres: {len(real_kb_ids)} real kb_article row(s), {len(real_message_ids)} real message row(s)")

    orphaned_ids: list[str] = []
    samples: list[str] = []
    total = 0
    next_offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=collection, with_payload=True, limit=200, offset=next_offset,
        )
        for point in points:
            total += 1
            reason = _is_orphaned(point.payload or {}, real_kb_ids, real_message_ids)
            if reason is not None:
                orphaned_ids.append(str(point.id))
                if len(samples) < 20:
                    samples.append(f"  {point.id}: {reason}")
        if next_offset is None:
            break

    print(f"scrolled {total} point(s); {len(orphaned_ids)} orphaned (test-written, no backing Postgres row)")
    if samples:
        print("samples:")
        print("\n".join(samples))
        if len(orphaned_ids) > len(samples):
            print(f"  ... and {len(orphaned_ids) - len(samples)} more")

    if not orphaned_ids:
        print("\nnothing to delete")
        return 0

    if not args.apply:
        print(f"\nDRY RUN — would delete {len(orphaned_ids)} point(s). Re-run with --apply to actually delete.")
        return 0

    client.delete(
        collection_name=collection,
        points_selector=models.PointIdsList(points=orphaned_ids),
    )
    after = client.get_collection(collection).points_count
    print(f"\ndeleted {len(orphaned_ids)} point(s) — collection now has {after} point(s) (was {before})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
