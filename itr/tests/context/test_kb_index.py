"""
KB article indexing + the case-OR-KB retrieval filter.

Two tiers, split deliberately so the logic that needs no infrastructure
always runs:

* OFFLINE (always run) — the filter-shape logic in retrieve.py and
  embed.py, the KB branch in compile.py, and kb_index's chunking/payload
  construction. Nothing here touches Qdrant, Postgres or OpenAI.
* LIVE (skip cleanly without Qdrant) — a real point with
  source_system="kb_article" round-trips through Qdrant, and — the test
  the original Part 6 would have hidden — a KB chunk surfaces on a
  retrieve() call that passes a REAL case_id, both alongside a matching
  case chunk and instead of one when none matches.

embed_query() is stubbed to a deterministic pseudo-vector in the live
tests (same precedent tests/context/test_pack.py set) so no OpenAI key is
needed; the Qdrant search, filter and payload round-trip are real.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest

from scout.canonical.models import KBArticle
from scout.config import settings
from scout.context import compile as compile_module
from scout.context import embed as embed_module
from scout.context import kb_index
from scout.context import retrieve as retrieve_module
from scout.context.chunk import Chunk
from scout.context.compile import compile as compile_pack
from scout.context.embed import EmbeddedChunk
from scout.context.retrieve import KB_SOURCE_SYSTEM, _build_acl_filter, retrieve

TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()
CASE_ID = uuid.uuid4()
ACL = [f"tenant:{TENANT_ID}", f"org:{uuid.uuid4()}"]


def make_article(**overrides) -> KBArticle:
    now = datetime.now(UTC)
    values = dict(
        id=uuid.uuid4(),
        category="licensing/activation",
        problem_class="license_key_invalid",
        title="Licence key rejected after renewal — INVALID_LICENSE_KEY on activation",
        body=(
            "The user renewed their subscription but activation returns INVALID_LICENSE_KEY. "
            "This usually means the new key was issued against the old account id.\n\n"
            "1. Confirm the renewal order shows status active.\n"
            "2. Regenerate the key from the licensing console.\n"
            "3. Ask the user to re-enter it and restart the client.\n\n"
            "Escalate to licensing if the regenerated key is also rejected."
        ),
        source="llm_generated",
        model_name="test-model",
        tenant_id=TENANT_ID,
        source_system=kb_index.KB_SOURCE_SYSTEM,
        external_id=None,
        is_synthetic=True,
        connector_run_id=uuid.uuid4(),
        observed_at=now,
        valid_from=now,
    )
    values.update(overrides)
    return KBArticle(**values)


# ══════════════════════════════════════════════════════════════════════════
# OFFLINE — always run
# ══════════════════════════════════════════════════════════════════════════


def test_kb_source_system_constant_is_shared_across_modules():
    """retrieve.py's OR group and kb_index's payload must agree, or KB points
    silently drop out of every case-scoped query again."""
    assert KB_SOURCE_SYSTEM == kb_index.KB_SOURCE_SYSTEM == compile_module._KB_SOURCE_SYSTEM


def test_retrieve_filter_is_case_or_kb_when_case_id_given():
    f = _build_acl_filter(ACL, CASE_ID)

    assert f["acl_tags"] == ACL, "ACL tags remain a hard AND"
    assert "case_id" not in f, "case_id must NOT be a top-level AND any more"
    groups = f["$should"]
    assert {"case_id": str(CASE_ID)} in groups
    kb_group = next(g for g in groups if g.get("source_system") == KB_SOURCE_SYSTEM)
    assert kb_group["acl_tags"] == [f"tenant:{TENANT_ID}"], "KB group is tenant-scoped, not org-scoped"


def test_retrieve_filter_without_case_id_has_no_should_group():
    f = _build_acl_filter(ACL, None)
    assert f == {"acl_tags": ACL}
    assert _build_acl_filter(None, None) is None


def test_embed_filter_translates_should_groups_into_qdrant_or():
    from qdrant_client import models

    qf = embed_module._build_acl_filter(
        {"acl_tags": ACL, "$should": [{"case_id": str(CASE_ID)}, {"source_system": KB_SOURCE_SYSTEM}]}
    )

    assert isinstance(qf, models.Filter)
    assert len(qf.must) == 1 and qf.must[0].key == "acl_tags"
    assert len(qf.should) == 2
    keys = {group.must[0].key for group in qf.should}
    assert keys == {"case_id", "source_system"}


def test_embed_filter_plain_dict_is_unchanged():
    """Regression: the pre-existing {field: value} shape still builds a pure must."""
    from qdrant_client import models

    qf = embed_module._build_acl_filter({"acl_tags": ACL, "case_id": "x"})
    assert isinstance(qf, models.Filter)
    assert len(qf.must) == 2 and qf.should is None


def test_kb_article_chunks_with_strict_off_and_carries_identifiers():
    # A body with an example e-mail inside a troubleshooting step would trip
    # chunk.looks_unredacted() under strict=True; kb_index passes strict=False.
    article = make_article(
        body="Ask the user to confirm the address on file, e.g. someone@example.com, then retry."
    )
    chunks = kb_index.chunk_article(article)

    assert chunks, "strict=False must let a KB body through"
    for chunk in chunks:
        assert chunk.message_id == article.id
        assert chunk.case_id is None and chunk.person_id is None
        assert chunk.acl_tags == [f"tenant:{TENANT_ID}"]
    full = f"{article.title}\n\n{article.body}"
    for chunk in chunks:
        assert full[chunk.start_offset:chunk.end_offset] == chunk.child_text


def test_kb_payload_shape_matches_email_payload_plus_discriminators():
    article = make_article()
    chunk = kb_index.chunk_article(article)[0]
    item = EmbeddedChunk(chunk=chunk, embedding=[0.0] * settings.embed_dims,
                         embedded_text=chunk.child_text, model="m", dims=settings.embed_dims)
    payload = kb_index._payload(article, item)

    # everything compile.py / trust_filter already read from an email payload
    for key in ("message_id", "case_id", "person_id", "acl_tags", "parent_text",
                "child_text", "start_offset", "end_offset"):
        assert key in payload
    assert payload["message_id"] == str(article.id), "reused field name carries the KB article id"
    assert payload["case_id"] is None
    assert payload["acl_tags"] == [f"tenant:{TENANT_ID}"]
    # discriminators
    assert payload["source_system"] == KB_SOURCE_SYSTEM
    assert payload["kb_article_id"] == str(article.id)


def test_kb_point_ids_are_deterministic_so_reindex_upserts():
    article = make_article()
    a = kb_index.chunk_article(article)
    b = kb_index.chunk_article(article)
    assert [kb_index._point_id(article.id, c) for c in a] == [kb_index._point_id(article.id, c) for c in b]


def test_compile_emits_article_citation_with_kb_timestamp(monkeypatch):
    """KB hit -> source_type='article', source_ts from kb_article, not from itr360.message."""
    article = make_article()
    kb_ts = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    email_id = uuid.uuid4()
    email_ts = datetime(2026, 8, 18, 14, 30, tzinfo=UTC)

    hits = [
        {
            "chunk_id": str(uuid.uuid4()), "score": 0.92,
            "payload": {"message_id": str(email_id), "case_id": str(CASE_ID), "person_id": None,
                        "acl_tags": ACL, "parent_text": "email parent", "child_text": "email child",
                        "start_offset": 0, "end_offset": 11},
        },
        {
            "chunk_id": str(uuid.uuid4()), "score": 0.88,
            "payload": {"message_id": str(article.id), "case_id": None, "person_id": None,
                        "acl_tags": [f"tenant:{TENANT_ID}"], "parent_text": "kb parent",
                        "child_text": "kb child", "start_offset": 0, "end_offset": 8,
                        "source_system": KB_SOURCE_SYSTEM, "kb_article_id": str(article.id)},
        },
    ]
    looked_up = {"message": None, "kb": None}

    def fake_sent_at(message_ids):
        looked_up["message"] = set(message_ids)
        return {str(email_id): email_ts}

    def fake_kb(article_ids):
        looked_up["kb"] = set(article_ids)
        return {str(article.id): kb_ts}

    monkeypatch.setattr(compile_module, "retrieve", lambda *a, **k: hits)
    monkeypatch.setattr(compile_module, "_lookup_sent_at", fake_sent_at)
    monkeypatch.setattr(compile_module, "_lookup_kb_observed_at", fake_kb)

    pack = compile_pack(intent="triage", case_id=CASE_ID, query_text="licence key invalid", acl_tags=ACL)

    assert looked_up["message"] == {str(email_id)}, "article id must not be looked up in itr360.message"
    assert looked_up["kb"] == {str(article.id)}
    by_type = {c.source_type: c for c in pack.citations}
    assert set(by_type) == {"comment", "article"}
    kb = by_type["article"]
    assert kb.source_system == KB_SOURCE_SYSTEM
    assert kb.source_ts == kb_ts
    assert kb.source_ts != compile_module._MISSING_SOURCE_TS_SENTINEL
    assert kb.to_dto()["access_status"] == "ok"
    assert kb.to_dto()["source_type"] == "article"
    assert kb.deep_link.startswith("kb://article/")
    assert by_type["comment"].source_ts == email_ts


# ══════════════════════════════════════════════════════════════════════════
# LIVE — skip cleanly without Qdrant
# ══════════════════════════════════════════════════════════════════════════


def _skip_if_qdrant_unreachable() -> None:
    try:
        from qdrant_client import QdrantClient
        QdrantClient(url=settings.qdrant_url).get_collections()
    except Exception:
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url} — skipping live KB index tests")


def _vector(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(settings.embed_dims)]


def _embedded(chunk: Chunk, seed: int) -> EmbeddedChunk:
    return EmbeddedChunk(chunk=chunk, embedding=_vector(seed), embedded_text=chunk.child_text,
                         model="test-model", dims=settings.embed_dims)


@pytest.fixture
def live(monkeypatch):
    _skip_if_qdrant_unreachable()
    # No OpenAI in the loop: deterministic pseudo-vectors keyed by a seed the
    # test controls. The Qdrant write/search/filter path is real.
    state = {"seed": 1}
    monkeypatch.setattr(retrieve_module, "embed_query", lambda text: _vector(state["seed"]))
    monkeypatch.setattr(kb_index, "embed_chunks",
                        lambda chunks, **kw: [_embedded(c, state["seed"]) for c in chunks])
    monkeypatch.setattr(kb_index.audit, "write", lambda **kw: uuid.uuid4())
    return state


def test_live_index_kb_article_writes_points_with_kb_source_system(live):
    live["seed"] = 101
    article = make_article()

    written = kb_index.index_kb_article(article)
    assert written >= 1

    hits = retrieve("licence key rejected", case_id=None, acl_tags=[f"tenant:{TENANT_ID}"], top_k=5)
    mine = [h for h in hits if h["payload"].get("kb_article_id") == str(article.id)]
    assert mine, "the KB point must be retrievable"
    assert mine[0]["payload"]["source_system"] == KB_SOURCE_SYSTEM


def test_live_kb_chunk_surfaces_on_a_real_case_id_query(live):
    """THE gap the original Part 6 would have hidden: a case-scoped retrieve()
    must return tenant-wide KB points, not filter them out server-side."""
    from scout.context.embed import upsert_chunks

    # One email chunk bound to CASE_ID, one KB article, both near the query vector.
    live["seed"] = 202
    email_chunk = Chunk(chunk_id=uuid.uuid4(), message_id=uuid.uuid4(), child_text="email text",
                        parent_text="email text", start_offset=0, end_offset=10, case_id=CASE_ID,
                        person_id=None, tenant_id=TENANT_ID, acl_tags=[f"tenant:{TENANT_ID}"])
    upsert_chunks([_embedded(email_chunk, 202)])
    article = make_article()
    kb_index.index_kb_article(article)

    hits = retrieve("anything", case_id=CASE_ID, acl_tags=[f"tenant:{TENANT_ID}"], top_k=10)
    sources = {h["payload"].get("source_system", "email") for h in hits}
    ids = {h["payload"].get("kb_article_id") for h in hits} | {h["payload"].get("message_id") for h in hits}

    assert str(email_chunk.message_id) in ids, "the case's own chunk still comes back"
    assert str(article.id) in ids, "and the KB chunk comes back ALONGSIDE it on a case-scoped query"
    assert KB_SOURCE_SYSTEM in sources


def test_live_kb_chunk_surfaces_instead_of_case_chunk_when_none_matches(live):
    live["seed"] = 303
    lonely_case = uuid.uuid4()  # no chunk in the index carries this case id
    article = make_article()
    kb_index.index_kb_article(article)

    hits = retrieve("anything", case_id=lonely_case, acl_tags=[f"tenant:{TENANT_ID}"], top_k=10)

    assert hits, "a case with no chunks of its own still gets KB evidence"
    assert all(h["payload"].get("case_id") in (None, str(lonely_case)) for h in hits), (
        "no OTHER case's chunks may leak in — the OR is case-or-KB, not case-or-anything"
    )
    assert any(h["payload"].get("kb_article_id") == str(article.id) for h in hits)


def test_live_kb_chunk_from_another_tenant_does_not_surface(live):
    live["seed"] = 404
    foreign = make_article(tenant_id=OTHER_TENANT_ID)
    kb_index.index_kb_article(foreign)

    hits = retrieve("anything", case_id=uuid.uuid4(), acl_tags=[f"tenant:{TENANT_ID}"], top_k=10)

    assert all(h["payload"].get("kb_article_id") != str(foreign.id) for h in hits), (
        "KB OR-group is tenant-scoped: another tenant's articles must not leak"
    )
