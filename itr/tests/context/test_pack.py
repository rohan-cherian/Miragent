"""
Task 18, Part 4 — tests for scout.context.compile.compile().

Skips cleanly (not a failure) if Qdrant isn't reachable at
settings.qdrant_url — same convention as tests/context/test_index.py.

compile() -> retrieve() -> embed_query() would otherwise need a live
OpenAI API key just to run these tests. embed_query is stubbed to a
deterministic pseudo-vector (same precedent test_index.py already
established for embed_chunks' vectors) so the query embedding step is
faked, but indexing (upsert_chunks), vector search (search), the ACL
gate (trust_filter), and budget compression (compile itself) all run
for real against the live Qdrant collection.
"""

from __future__ import annotations

import random
import uuid

import pytest
from qdrant_client import QdrantClient

from scout.config import settings
from scout.context import compile as compile_module
from scout.context.chunk import Chunk
from scout.context.compile import compile as compile_pack
from scout.context.embed import EmbeddedChunk, upsert_chunks


def _skip_if_qdrant_unreachable() -> None:
    try:
        QdrantClient(url=settings.qdrant_url).get_collections()
    except Exception:
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url} — skipping context-pack tests")


@pytest.fixture(autouse=True)
def _require_qdrant():
    _skip_if_qdrant_unreachable()


def _make_vector(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(settings.embed_dims)]


def _make_embedded_chunk(
    seed: int, text: str, case_id, message_id, acl_tags: list[str]
) -> EmbeddedChunk:
    chunk = Chunk(
        chunk_id=uuid.uuid4(),
        message_id=message_id,
        child_text=text,
        parent_text=text,
        start_offset=0,
        end_offset=len(text),
        case_id=case_id,
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


def test_no_matching_chunks_yields_low_context_pack(monkeypatch):
    monkeypatch.setattr(compile_module, "retrieve", lambda *a, **k: [])

    pack = compile_pack(
        intent="test",
        case_id=uuid.uuid4(),
        query_text="anything",
        acl_tags=[f"tenant:{uuid.uuid4()}"],
    )

    assert pack.low_context is True
    assert pack.citations == []


def test_citations_fit_low_token_budget_and_excerpts_match_source_exactly(monkeypatch):
    marker = f"tenant:{uuid.uuid4()}"
    case_id = uuid.uuid4()
    message_id_a = uuid.uuid4()
    message_id_b = uuid.uuid4()

    text_a = "Short excerpt A. " * 5
    text_b = "Short excerpt B. " * 5

    hits = [
        {
            "chunk_id": str(uuid.uuid4()),
            "score": 0.95,
            "payload": {
                "message_id": str(message_id_a),
                "acl_tags": [marker],
                "parent_text": text_a,
                "child_text": text_a,
            },
        },
        {
            "chunk_id": str(uuid.uuid4()),
            "score": 0.90,
            "payload": {
                "message_id": str(message_id_b),
                "acl_tags": [marker],
                "parent_text": text_b,
                "child_text": text_b,
            },
        },
    ]

    monkeypatch.setattr(compile_module, "retrieve", lambda *a, **k: hits)
    monkeypatch.setattr(compile_module, "_lookup_sent_at", lambda message_ids: {})
    # low enough to fit exactly one of the two citations, never a fragment of one
    tokens_for_one = max(1, len(text_a) // compile_module._CHARS_PER_TOKEN)
    monkeypatch.setattr(settings, "token_budget", tokens_for_one)

    pack = compile_pack(
        intent="test", case_id=case_id, query_text="anything", acl_tags=[marker]
    )

    assert len(pack.citations) == 1
    assert pack.citations[0].excerpt == text_a  # exact source text, never truncated
    assert pack.token_count <= tokens_for_one


def test_citations_trace_back_to_real_upserted_chunk_and_message_ids(monkeypatch):
    marker = f"tenant:{uuid.uuid4()}"
    case_id = uuid.uuid4()
    message_id = uuid.uuid4()
    text = "The office is closed for the holiday schedule next week."

    target = _make_embedded_chunk(
        seed=42, text=text, case_id=case_id, message_id=message_id, acl_tags=[marker]
    )
    upsert_chunks([target])

    monkeypatch.setattr(
        "scout.context.retrieve.embed_query", lambda query_text: target.embedding
    )

    pack = compile_pack(
        intent="test", case_id=case_id, query_text="holiday schedule", acl_tags=[marker]
    )

    assert not pack.low_context
    assert len(pack.citations) >= 1
    top = pack.citations[0]
    assert top.chunk_id == str(target.chunk_id)
    assert top.message_id == str(message_id)
    assert top.excerpt == text


def test_compile_calls_retrieve_exactly_once(monkeypatch):
    call_count = 0

    def _counting_retrieve(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr(compile_module, "retrieve", _counting_retrieve)

    compile_pack(
        intent="test",
        case_id=uuid.uuid4(),
        query_text="anything",
        acl_tags=[f"tenant:{uuid.uuid4()}"],
    )

    assert call_count == 1


def test_citation_with_no_matching_message_row_serialises_with_missing_status():
    """Orphaned chunk: its message_id has no matching itr360.message row,
    so _lookup_sent_at() never fills in a real source_ts and it stays
    None on the Citation. to_dto() must degrade to a sentinel timestamp
    and access_status='missing' rather than raising AttributeError on
    None.isoformat() (the bug worked around defensively in
    scout/agents/resolve.py's _evidence_dtos(), fixed at the source
    here)."""
    citation = compile_module.Citation(
        source_system="gmail",
        source_type="comment",
        object_id=str(uuid.uuid4()),
        excerpt="orphaned chunk text",
        source_ts=None,
        deep_link="https://mail.google.com/mail/u/0/#all/x",
        access_status="ok",
    )

    dto = citation.to_dto()  # must not raise

    assert dto["access_status"] == "missing"
    assert dto["source_ts"] == compile_module._MISSING_SOURCE_TS_SENTINEL.isoformat()
