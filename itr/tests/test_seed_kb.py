"""
Task 0, Part 5 — scripts/seed_kb.py.

Skips cleanly without a live database (this repo's convention — see
tests/canonical/test_identity.py's _make_engine()). A second, narrower tier
additionally needs Qdrant reachable and skips just that one test if not.

Uses its own throwaway problem_taxonomy row (category "TST0") rather than
depending on scripts/seed_taxonomy.py having been run first, so these tests
are independent of run order and clean up after themselves.

Every test in this module talks to a live Postgres, so the whole module is
marked `@pytest.mark.live` (registered in pyproject.toml) — a default run
that excludes live tests (`pytest -m "not live"`) never depends on external
state. The one Qdrant-dependent test additionally isolates itself into a
dedicated test collection (see `_isolated_qdrant_collection` below) rather
than writing into the shared dev collection — see the flake postmortem in
that fixture's docstring for why.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scout.canonical.models import KBArticle, ProblemTaxonomy
from scout.config import settings
from scripts import seed_kb as seed_kb_module

pytestmark = pytest.mark.live

TEST_CATEGORY = "TST0"
TEST_PROBLEM_CLASS = "TST0-01"
TEST_KB_ID = "TEST-KB-TST0-01"

FIXTURE_MD = f"""---
kb_id: {TEST_KB_ID}
title: Test fixture article for seed_kb
problem_class: {TEST_PROBLEM_CLASS}
category: {TEST_CATEGORY}
last_updated: 2026-08-01
---
## Symptom
This is a throwaway fixture article used only by tests/test_seed_kb.py.

## Cause
It exists so the seed_kb pipeline can be exercised without depending on
the real data/kb_articles content or the real taxonomy being seeded first.

## Resolution
1. Nothing to do — this is test fixture content, not real guidance.

## If this doesn't work
This article is never meant to surface in a real retrieve() call outside
of this test's own assertions.
"""

BAD_MD = """---
kb_id: TEST-KB-UNSEEDED
title: Article for an unseeded problem class
problem_class: ZZZ-99
category: ZZZ
last_updated: 2026-08-01
---
## Symptom
This class was never seeded into problem_taxonomy on purpose.
"""


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except Exception:
        pytest.skip("No live database available — skipping seed_kb tests")
    return engine


@pytest.fixture
def db():
    engine = _make_engine()

    with Session(engine) as session:
        session.add(
            ProblemTaxonomy(
                id=uuid.uuid4(),
                category=TEST_CATEGORY,
                problem_class=TEST_PROBLEM_CLASS,
                description="Throwaway taxonomy row for seed_kb tests",
                example_phrases=None,
                default_priority="low",
            )
        )
        session.commit()

    yield engine

    with Session(engine) as session:
        for article in session.execute(
            select(KBArticle).where(KBArticle.category.in_([TEST_CATEGORY, "ZZZ"]))
        ).scalars():
            session.delete(article)
        for row in session.execute(
            select(ProblemTaxonomy).where(ProblemTaxonomy.category == TEST_CATEGORY)
        ).scalars():
            session.delete(row)
        session.commit()


@pytest.fixture
def no_index(monkeypatch):
    """Stub out kb_index.index_kb_article so these tests need Postgres but
    not Qdrant/OpenAI — only the row-upsert behavior is under test here."""
    monkeypatch.setattr(seed_kb_module, "index_kb_article", lambda article: 3)


def _write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_seeding_creates_one_kb_article_row(db, no_index, tmp_path, monkeypatch):
    _write(tmp_path, "fixture.md", FIXTURE_MD)
    monkeypatch.setattr(seed_kb_module, "KB_ARTICLES_DIR", tmp_path)

    rc = seed_kb_module.main()
    assert rc == 0

    with Session(db) as session:
        rows = session.execute(
            select(KBArticle).where(KBArticle.external_id == TEST_KB_ID)
        ).scalars().all()

    assert len(rows) == 1
    assert rows[0].external_id == TEST_KB_ID
    assert rows[0].source == "hand_written"


def test_rerunning_does_not_create_a_second_row(db, no_index, tmp_path, monkeypatch):
    _write(tmp_path, "fixture.md", FIXTURE_MD)
    monkeypatch.setattr(seed_kb_module, "KB_ARTICLES_DIR", tmp_path)

    assert seed_kb_module.main() == 0
    assert seed_kb_module.main() == 0

    with Session(db) as session:
        rows = session.execute(
            select(KBArticle).where(KBArticle.external_id == TEST_KB_ID)
        ).scalars().all()

    assert len(rows) == 1, "upsert on (tenant_id, external_id) must not duplicate on re-run"


def test_unseeded_problem_class_fails_with_a_clear_message_not_a_traceback(
    db, no_index, tmp_path, monkeypatch, capsys
):
    _write(tmp_path, "bad.md", BAD_MD)
    monkeypatch.setattr(seed_kb_module, "KB_ARTICLES_DIR", tmp_path)

    rc = seed_kb_module.main()
    out = capsys.readouterr().out

    assert rc == 1
    assert "seed_taxonomy" in out, "failure must point back at seed_taxonomy.py, not a raw traceback"
    assert "ZZZ/ZZZ-99" in out

    with Session(db) as session:
        rows = session.execute(
            select(KBArticle).where(KBArticle.external_id == "TEST-KB-UNSEEDED")
        ).scalars().all()
    assert rows == [], "a failed insert must not leave a partial row behind"


# ══════════════════════════════════════════════════════════════════════════
# LIVE — additionally needs Qdrant reachable
# ══════════════════════════════════════════════════════════════════════════


TEST_QDRANT_COLLECTION = "itr360_chunks_test"


def _skip_if_qdrant_unreachable() -> None:
    try:
        from qdrant_client import QdrantClient

        QdrantClient(url=settings.qdrant_url).get_collections()
    except Exception:
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url} — skipping live seed_kb test")


@pytest.fixture
def _isolated_qdrant_collection(monkeypatch):
    """Point every Qdrant call this test makes at a dedicated, disposable
    test collection instead of the shared dev collection.

    Postmortem: this test used to write into settings.qdrant_collection_name
    (the same collection real /context-pack calls and every other live test
    in the repo share) and then assert its own article ranked in the top_k
    of an UNFILTERED similarity search. That made the assertion a function
    of every point anyone had ever upserted — it passed in isolation and
    failed inside the full suite as the shared collection grew. Writing into
    a private collection removes the shared-state dependency; see also the
    rank-independent (filtered-search) assertion below, which removes the
    other half of the problem — even within this private collection, the
    test no longer depends on vector-similarity RANK, only on presence.

    settings.qdrant_collection_name is read fresh on every call by
    scout.context.embed (ensure_collection/upsert_chunks/search/
    collection_stats) and scout.context.kb_index.index_kb_article, so
    monkeypatching it here before the test body runs is sufficient — no
    client-level caching to worry around.
    """
    monkeypatch.setattr(settings, "qdrant_collection_name", TEST_QDRANT_COLLECTION)

    yield TEST_QDRANT_COLLECTION

    from qdrant_client import QdrantClient

    client = QdrantClient(url=settings.qdrant_url)
    if client.collection_exists(TEST_QDRANT_COLLECTION):
        client.delete_collection(TEST_QDRANT_COLLECTION)


def test_live_seeded_article_is_retrievable_by_kb_article_id(
    db, tmp_path, monkeypatch, _isolated_qdrant_collection
):
    """After seeding, the article's point is retrievable by a payload
    filter on kb_article_id — the real proof that seed_kb goes through
    kb_index (which writes that payload key) and not some parallel path.

    Filtered by kb_article_id rather than by unfiltered top_k rank: rank
    against a similarity search is not what "retrievable by kb_article_id"
    claims, and is a function of whatever else shares the collection (see
    _isolated_qdrant_collection's docstring). A payload filter exercises
    the exact mechanism production KB retrieval actually depends on
    (embed._build_acl_filter's scalar -> MatchValue translation) without
    being sensitive to what else is indexed.
    """
    _skip_if_qdrant_unreachable()

    import random

    from scout.context import embed as embed_module
    from scout.context import kb_index as kb_index_module
    from scout.context.embed import EmbeddedChunk

    def vector(seed: int) -> list[float]:
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(settings.embed_dims)]

    def fake_embed_chunks(chunks, **kw):
        return [
            EmbeddedChunk(
                chunk=c, embedding=vector(999), embedded_text=c.child_text,
                model="test-model", dims=settings.embed_dims,
            )
            for c in chunks
        ]

    monkeypatch.setattr(kb_index_module, "embed_chunks", fake_embed_chunks)
    monkeypatch.setattr(kb_index_module.audit, "write", lambda **kw: uuid.uuid4())

    _write(tmp_path, "fixture.md", FIXTURE_MD)
    monkeypatch.setattr(seed_kb_module, "KB_ARTICLES_DIR", tmp_path)

    assert seed_kb_module.main() == 0

    with Session(db) as session:
        row = session.execute(
            select(KBArticle).where(KBArticle.external_id == TEST_KB_ID)
        ).scalar_one()
        article_id = str(row.id)

    hits = embed_module.search(
        query_embedding=vector(999),
        top_k=10,
        acl_filter={"kb_article_id": article_id},
    )

    assert hits, "the seeded article must be retrievable via a kb_article_id filter"
    payload = hits[0]["payload"]
    assert payload["source_system"] == "kb_article"
    assert payload["kb_article_id"] == article_id
    assert payload["acl_tags"] == [f"tenant:{settings.tenant_id}"]
    assert payload["parent_text"] and payload["child_text"]
    assert isinstance(payload["start_offset"], int)
    assert isinstance(payload["end_offset"], int)
