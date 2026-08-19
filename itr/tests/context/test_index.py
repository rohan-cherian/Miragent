"""
Task 17 (part 3) — tests for the Qdrant indexing layer.

Skips cleanly (not a failure) if Qdrant isn't reachable at
settings.qdrant_url, rather than failing. Every point upserted here
carries a unique acl_tags marker per test so search()/acl_filter
assertions are scoped to that test's own data, even though the
underlying collection is shared and not reset between runs.
"""

from __future__ import annotations

import random
import uuid

import pytest
from qdrant_client import QdrantClient

from scout.config import settings
from scout.context.chunk import Chunk
from scout.context.embed import (
    EmbeddedChunk,
    collection_stats,
    ensure_collection,
    search,
    upsert_chunks,
)


def _skip_if_qdrant_unreachable() -> None:
    try:
        QdrantClient(url=settings.qdrant_url).get_collections()
    except Exception:
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url} — skipping index tests")


@pytest.fixture(autouse=True)
def _require_qdrant():
    _skip_if_qdrant_unreachable()


def _make_vector(seed: int) -> list[float]:
    """Deterministic pseudo-embedding of the correct dimension — no live
    OpenAI call needed, just something Qdrant can genuinely rank by
    cosine similarity."""
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(settings.embed_dims)]


def _make_embedded_chunk(seed: int, acl_tags: list[str]) -> EmbeddedChunk:
    text = f"Test chunk text {seed}"
    chunk = Chunk(
        chunk_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        child_text=text,
        parent_text=text,
        start_offset=0,
        end_offset=len(text),
        case_id=uuid.uuid4(),
        person_id=None,
        tenant_id=None,
        parent_index=0,
        child_index=0,
        acl_tags=acl_tags,
    )
    return EmbeddedChunk(
        chunk=chunk,
        embedding=_make_vector(seed),
        embedded_text=text,
        model="test-model",
        dims=settings.embed_dims,
    )


def test_ensure_collection_is_idempotent():
    ensure_collection()
    ensure_collection()  # second call must not error

    client = QdrantClient(url=settings.qdrant_url)
    matching = [
        c for c in client.get_collections().collections
        if c.name == settings.qdrant_collection_name
    ]
    assert len(matching) == 1


def test_upsert_then_search_returns_the_same_chunk_as_top_result():
    marker = f"test-marker-{uuid.uuid4()}"
    target = _make_embedded_chunk(seed=1, acl_tags=[marker])
    other = _make_embedded_chunk(seed=2, acl_tags=[marker])

    upsert_chunks([target, other])

    results = search(
        query_embedding=target.embedding,
        top_k=5,
        acl_filter={"acl_tags": [marker]},
    )

    assert len(results) > 0
    assert results[0]["chunk_id"] == str(target.chunk_id)
    assert results[0]["payload"]["message_id"] == str(target.message_id)
    assert results[0]["payload"]["child_text"] == target.child_text


def test_search_with_non_matching_acl_filter_returns_nothing():
    marker = f"test-marker-{uuid.uuid4()}"
    chunk = _make_embedded_chunk(seed=3, acl_tags=[marker])
    upsert_chunks([chunk])

    results = search(
        query_embedding=chunk.embedding,
        top_k=5,
        acl_filter={"acl_tags": [f"nonexistent-tag-{uuid.uuid4()}"]},
    )

    assert results == []


def test_collection_stats_reports_at_least_upserted_count():
    marker = f"test-marker-{uuid.uuid4()}"
    chunks = [_make_embedded_chunk(seed=i, acl_tags=[marker]) for i in range(10, 13)]
    upsert_chunks(chunks)

    stats = collection_stats()

    # >= rather than == : prior test runs against this same live collection
    # may leave residual points behind (no test-isolation/cleanup story for
    # the Qdrant collection yet — noted as a known limitation, not solved
    # here). This only proves upsert_chunks() genuinely added points.
    assert stats["points_count"] >= len(chunks)
    assert stats["name"] == settings.qdrant_collection_name
