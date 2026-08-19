"""
Task 17 — tests for embed_chunks().

Two layers:

* **Offline** — the batching, retry, skip and audit behaviour, exercised by
  monkeypatching the HTTP layer. These always run; no key, no network, no
  database.
* **Live** — one test that actually calls OpenAI. It skips cleanly (never
  fails) when settings.openai_api_key is empty, which is the normal state in
  CI and on a laptop without .env.local.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from scout.config import settings
from scout.context import embed as embed_module
from scout.context.chunk import Chunk
from scout.context.embed import EmbeddedChunk, EmbeddingError, embed_chunks

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TENANT_ID = uuid.uuid4()
CASE_ID = uuid.uuid4()
MESSAGE_ID = uuid.uuid4()


def make_chunk(text: str, index: int = 0) -> Chunk:
    return Chunk(
        chunk_id=uuid.uuid4(),
        message_id=MESSAGE_ID,
        child_text=text,
        parent_text=text,
        start_offset=0,
        end_offset=len(text),
        case_id=CASE_ID,
        person_id=None,
        tenant_id=TENANT_ID,
        parent_index=0,
        child_index=index,
        acl_tags=[f"tenant:{TENANT_ID}"],
    )


SAMPLE_CHUNKS = [
    make_chunk("My licence key stopped working after the renewal.", 0),
    make_chunk("Could someone reissue it before Friday's release?", 1),
    make_chunk("Billing has already taken the payment for the year.", 2),
]


@pytest.fixture(autouse=True)
def no_redaction_engine(monkeypatch):
    """Skip Presidio in unit tests — the redaction pass has its own suite (Task 12)."""
    class _Result:
        def __init__(self, text: str) -> None:
            self.text = text
            self.pii_map: dict[str, str] = {}
            self.status = "clean"

    monkeypatch.setattr(embed_module, "redact", lambda text: _Result(text))


@pytest.fixture(autouse=True)
def api_key(monkeypatch, request):
    """Offline tests get a dummy key. The live test keeps the real one."""
    if request.node.name.startswith("test_live_"):
        return
    monkeypatch.setattr(settings, "openai_api_key", "test-key", raising=False)


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    monkeypatch.setattr(embed_module.time, "sleep", lambda _seconds: None)


def fake_vector() -> list[float]:
    """A vector of exactly the pinned dimension — never a hardcoded 1024."""
    return [0.01] * settings.embed_dims


def install_transport(monkeypatch, handler):
    """Point embed._client() at a MockTransport running `handler`."""
    real_client = httpx.Client

    def _client():
        return real_client(
            base_url=settings.embed_base_url.rstrip("/"),
            transport=httpx.MockTransport(handler),
            timeout=5.0,
        )

    monkeypatch.setattr(embed_module, "_client", _client)


# ── Happy path ────────────────────────────────────────────────────────────


def test_embeddings_have_exactly_embed_dims_length(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["model"] == settings.embed_model
        assert payload["dimensions"] == settings.embed_dims
        inputs = payload["input"]
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": fake_vector()} for i in range(len(inputs))]},
        )

    install_transport(monkeypatch, handler)

    result = embed_chunks(SAMPLE_CHUNKS, write_audit=False)

    assert len(result) == len(SAMPLE_CHUNKS)
    assert all(isinstance(item, EmbeddedChunk) for item in result)
    for item in result:
        assert len(item.embedding) == settings.embed_dims
        assert item.dims == settings.embed_dims
        assert item.model == settings.embed_model


def test_child_text_is_embedded_not_parent_text(monkeypatch):
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        seen.append(inputs)
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": fake_vector()} for i in range(len(inputs))]},
        )

    install_transport(monkeypatch, handler)

    chunk = Chunk(
        chunk_id=uuid.uuid4(),
        message_id=MESSAGE_ID,
        child_text="reissue the licence key",
        parent_text="A much longer paragraph that should never be embedded.",
        start_offset=0,
        end_offset=23,
    )
    embed_chunks([chunk], write_audit=False)

    assert seen == [["reissue the licence key"]]


def test_requests_are_batched_by_embed_batch(monkeypatch):
    monkeypatch.setattr(settings, "embed_batch", 2, raising=False)
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        calls.append(len(inputs))
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": fake_vector()} for i in range(len(inputs))]},
        )

    install_transport(monkeypatch, handler)

    chunks = [make_chunk(f"sentence number {i}", i) for i in range(5)]
    result = embed_chunks(chunks, write_audit=False)

    assert calls == [2, 2, 1]
    assert len(result) == 5


def test_empty_input_makes_no_call(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("embed_chunks() should not call the API for an empty list")

    install_transport(monkeypatch, handler)
    assert embed_chunks([], write_audit=False) == []


# ── Failure handling: retry once, then SKIP the batch ─────────────────────


def test_transient_failure_is_retried_once_and_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        inputs = json.loads(request.read())["input"]
        if attempts["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": fake_vector()} for i in range(len(inputs))]},
        )

    install_transport(monkeypatch, handler)

    result = embed_chunks(SAMPLE_CHUNKS, write_audit=False)

    assert attempts["n"] == 2, "expected exactly one retry"
    assert len(result) == len(SAMPLE_CHUNKS)


def test_persistent_batch_failure_is_skipped_not_raised(monkeypatch, caplog):
    """Documented strategy: retry once with backoff, then skip the batch."""
    monkeypatch.setattr(settings, "embed_batch", 2, raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        if any("poison" in text for text in inputs):
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": fake_vector()} for i in range(len(inputs))]},
        )

    install_transport(monkeypatch, handler)

    chunks = [
        make_chunk("good one", 0),
        make_chunk("poison pill", 1),   # batch 1 -> always 500
        make_chunk("good two", 2),
        make_chunk("good three", 3),    # batch 2 -> fine
    ]

    with caplog.at_level("ERROR"):
        result = embed_chunks(chunks, write_audit=False)

    # The whole run survives; only the failing batch is missing.
    assert len(result) == 2
    assert {item.child_text for item in result} == {"good two", "good three"}
    assert any("SKIPPED" in record.message for record in caplog.records)


def test_a_raising_embedding_call_does_not_crash_the_run(monkeypatch, caplog):
    """Simulated hard failure of the embedding call itself."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    install_transport(monkeypatch, handler)

    with caplog.at_level("ERROR"):
        result = embed_chunks(SAMPLE_CHUNKS, write_audit=False)

    assert result == []
    assert any("SKIPPED" in record.message for record in caplog.records)


def test_wrong_dimension_response_is_rejected(monkeypatch, caplog):
    """A vector that is not settings.embed_dims long must never reach the index."""
    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [0.0] * (settings.embed_dims - 1)}
                    for i in range(len(inputs))
                ]
            },
        )

    install_transport(monkeypatch, handler)

    with caplog.at_level("ERROR"):
        result = embed_chunks(SAMPLE_CHUNKS, write_audit=False)

    assert result == []


def test_missing_api_key_raises_a_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)

    with pytest.raises(EmbeddingError) as excinfo:
        embed_chunks(SAMPLE_CHUNKS, write_audit=False)

    assert "OPENAI_API_KEY" in str(excinfo.value)


# ── Audit: one row per message, not per chunk ─────────────────────────────


def test_one_audit_row_per_message_not_per_chunk(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": fake_vector()} for i in range(len(inputs))]},
        )

    install_transport(monkeypatch, handler)

    written: list[dict] = []
    monkeypatch.setattr(
        embed_module.audit, "write", lambda **kwargs: written.append(kwargs) or uuid.uuid4()
    )

    embed_chunks(SAMPLE_CHUNKS, write_audit=True)

    assert len(written) == 1, "three chunks from one message must produce one audit row"
    row = written[0]
    assert row["category"] == "system"
    assert row["action"] == "embed_chunks"
    assert row["outputs"]["chunk_count"] == 3
    assert row["outputs"]["message_id"] == str(MESSAGE_ID)


def test_audit_failure_does_not_lose_completed_embeddings(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["input"]
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": fake_vector()} for i in range(len(inputs))]},
        )

    install_transport(monkeypatch, handler)

    def _boom(**_kwargs):
        raise RuntimeError('relation "itr360.decision_audit" does not exist')

    monkeypatch.setattr(embed_module.audit, "write", _boom)

    with caplog.at_level("ERROR"):
        result = embed_chunks(SAMPLE_CHUNKS, write_audit=True)

    assert len(result) == len(SAMPLE_CHUNKS)
    assert any("decision_audit" in record.message for record in caplog.records)


# ── Live call — skipped cleanly when no key is configured ─────────────────


@pytest.mark.skipif(
    not settings.openai_api_key,
    reason="No OPENAI_API_KEY configured — skipping live embeddings call",
)
def test_live_embeddings_return_pinned_dimension():
    from scout.context.chunk import chunk_message

    chunks = chunk_message(
        {
            "id": MESSAGE_ID,
            "case_id": CASE_ID,
            "tenant_id": TENANT_ID,
            "body_redacted": "My licence key stopped working after the renewal.",
        }
    )
    result = embed_chunks(chunks, write_audit=False)

    assert result
    for item in result:
        assert len(item.embedding) == settings.embed_dims
        assert item.model == settings.embed_model
