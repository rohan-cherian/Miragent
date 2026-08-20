"""
Index Knowledge Base articles into the SAME Qdrant collection Task 17 uses.

This is the concrete proof that the chunk -> embed -> index -> retrieve ->
trust -> compile pipeline is source-agnostic: a second content type goes
through it with no change to chunk.py, embed.py, trust.py or the agents.

How a KB article becomes points
-------------------------------
* ``chunk_message()`` from Task 17, fed a dict shaped like a canonical
  message (``id``, ``body_redacted``, ``tenant_id``, ``case_id=None``,
  ``person_id=None``). It is called with ``strict=False``: KB bodies may
  legitimately contain an example e-mail address or a sample 16-digit
  number inside a troubleshooting step, which would trip
  ``chunk.looks_unredacted()``. That is not a governance gap —
  ``embed_chunks()`` still runs its own ``pii.redact()`` pass on every
  child text before anything is sent to the embeddings endpoint, exactly
  as it does for email chunks.
* ``embed_chunks()`` from Task 17, unchanged (``write_audit=False`` — the
  per-message ``embed_chunks`` audit row is meant for ingest; this module
  writes one ``kb_indexed`` row per article instead, so the audit trail
  stays at the article grain).
* Point construction and upsert are done HERE, not via
  ``embed.upsert_chunks()``. That function's payload is a fixed key set
  (``embed._chunk_payload``) with no room for ``source_system`` /
  ``kb_article_id``, and embed.py is a pinned Task 17 module. This is a
  deliberate, scoped duplication of ~15 lines — accepted as such, not a
  TODO to unify later.

Payload shape
-------------
Identical to an email chunk's payload so that trust_filter() and
compile() read it without special-casing, plus two discriminators:

    message_id      = str(article.id)   <- REUSED FIELD NAME. compile.py
                                           keys its source_ts lookup and
                                           object_id on payload["message_id"];
                                           reusing the name keeps that path
                                           working for KB points. It is the
                                           KB article id, not an itr360.message
                                           id — compile.py branches on
                                           source_system to tell them apart.
    case_id         = None               <- tenant-wide, not case-bound
    person_id       = None
    acl_tags        = ["tenant:<tenant id>"]
    parent_text / child_text / start_offset / end_offset
    source_system   = "kb_article"       <- what retrieve.py's OR group
                                           and compile.py branch on
    kb_article_id   = str(article.id)    <- explicit, for anyone who
                                           doesn't want to decode the reuse

Idempotency
-----------
``index_all_kb_articles()`` re-indexes everything every run. There is no
"indexed" marker column on kb_article (adding one is out of scope), and
Qdrant upsert is idempotent on point id — so the cost of the simple
approach is one embedding pass per article per run, and the benefit is
that a changed body is always re-embedded. Point ids are deterministic
(uuid5 over article id + offsets), so re-runs overwrite rather than
duplicate — unlike Task 17's uuid4 chunk ids, which are out of scope to
change here.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client import models
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical.models import KBArticle
from scout.config import settings
from scout.context import embed as embed_module
from scout.context.chunk import Chunk, chunk_message
from scout.context.embed import EmbeddedChunk, embed_chunks, ensure_collection
from scout.governance import audit

logger = logging.getLogger(__name__)

KB_SOURCE_SYSTEM = "kb_article"

# Stable namespace so the same (article, span) always maps to the same
# point id -> upsert overwrites instead of duplicating.
_POINT_NAMESPACE = uuid.UUID("9b1e0a7c-4d52-4b7e-8f8a-7c6f6d4c1b21")

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def _tenant_tag(tenant_id: Any) -> str:
    return f"tenant:{tenant_id}"


def _as_message_dict(article: KBArticle) -> dict[str, Any]:
    """Shape a KB article like a canonical message for chunk_message()."""
    return {
        "id": article.id,
        "case_id": None,
        "person_id": None,
        "tenant_id": article.tenant_id,
        "subject": article.title,
        # title + body, so the title's wording is searchable too.
        "body_redacted": f"{article.title}\n\n{article.body}",
    }


def _point_id(article_id: Any, chunk: Chunk) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{article_id}:{chunk.start_offset}:{chunk.end_offset}"))


def _payload(article: KBArticle, item: EmbeddedChunk) -> dict[str, Any]:
    return {
        "message_id": str(article.id),  # reused name — see module docstring
        "case_id": None,
        "person_id": None,
        "acl_tags": [_tenant_tag(article.tenant_id)],
        "parent_text": item.parent_text,
        "child_text": item.child_text,
        "start_offset": item.start_offset,
        "end_offset": item.end_offset,
        "source_system": KB_SOURCE_SYSTEM,
        "kb_article_id": str(article.id),
        "category": article.category,
        "problem_class": article.problem_class,
        "title": article.title,
    }


def chunk_article(article: KBArticle) -> list[Chunk]:
    """KB article -> Chunks, via Task 17's chunk_message (strict=False — see docstring)."""
    return chunk_message(_as_message_dict(article), strict=False)


def index_kb_article(article: KBArticle) -> int:
    """Chunk, embed and upsert one article. Returns the number of points written."""
    chunks = chunk_article(article)
    if not chunks:
        logger.warning("kb_index: article %s has no chunkable body — skipped", article.id)
        return 0

    embedded = embed_chunks(chunks, write_audit=False)
    if not embedded:
        logger.error("kb_index: article %s produced no embeddings — not indexed", article.id)
        return 0

    ensure_collection()
    points = [
        models.PointStruct(
            id=_point_id(article.id, item.chunk),
            vector=item.embedding,
            payload=_payload(article, item),
        )
        for item in embedded
    ]
    client = embed_module._get_qdrant_client()
    client.upsert(collection_name=settings.qdrant_collection_name, points=points)

    try:
        audit.write(
            actor="scout.context.kb_index",
            action="kb_indexed",
            category="system",
            outputs={
                "kb_article_id": str(article.id),
                "category": article.category,
                "problem_class": article.problem_class,
                "point_count": len(points),
                "model": settings.embed_model,
                "dims": settings.embed_dims,
            },
        )
    except Exception as exc:  # noqa: BLE001 — indexing succeeded; log, don't undo
        logger.error("kb_index: audit row failed for %s — %s: %s", article.id, type(exc).__name__, exc)

    return len(points)


def index_all_kb_articles(*, tenant_id: Any = None) -> dict[str, int]:
    """Re-index every KBArticle (see docstring for why every, not only new)."""
    tenant = uuid.UUID(str(tenant_id or settings.tenant_id))
    with Session(_get_engine()) as session:
        articles = session.execute(
            select(KBArticle)
            .where(KBArticle.tenant_id == tenant)
            .order_by(KBArticle.category, KBArticle.problem_class, KBArticle.title)
        ).scalars().all()
        articles = list(articles)
        for article in articles:
            session.expunge(article)

    totals = {"articles": len(articles), "indexed": 0, "points": 0, "failed": 0}
    for article in articles:
        try:
            points = index_kb_article(article)
        except Exception as exc:  # noqa: BLE001 — one bad article must not stop the run
            totals["failed"] += 1
            logger.error("kb_index: %s failed — %s: %s", article.id, type(exc).__name__, exc)
            continue
        if points:
            totals["indexed"] += 1
            totals["points"] += points

    logger.info("kb_index: %(articles)d articles, %(indexed)d indexed, %(points)d points, %(failed)d failed", totals)
    return totals


__all__ = [
    "KB_SOURCE_SYSTEM",
    "chunk_article",
    "index_all_kb_articles",
    "index_kb_article",
]
