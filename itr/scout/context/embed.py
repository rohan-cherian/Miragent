"""
Task 17 (part 2) — embed the child chunks.

Takes the :class:`~scout.context.chunk.Chunk` objects produced by
``chunk_message()`` and returns :class:`EmbeddedChunk` objects carrying a
vector of exactly ``settings.embed_dims`` floats.

Design notes
------------
* **Child text only.** Parents are context for display; children are what
  gets searched. Embedding the parent would blur the vector and break the
  "retrieved sentence arrives with its surroundings" property.
* **OpenAI direct.** OpenRouter routes chat/completions only — it has no
  ``/embeddings`` endpoint (Task 3). Base URL, model and dimension all come
  from ``scout.config.settings``; none of them is written as a literal here.
  The call goes over ``httpx`` (already a project dependency) rather than
  the ``openai`` SDK, because Task 17 adds no dependency to pyproject.toml.
  The request body is the SDK's own ``embeddings.create`` shape
  (``model`` / ``input`` (list) / ``dimensions``), so swapping in the SDK
  later is a one-function change inside ``_post_embeddings``.
* **Batched.** ``settings.embed_batch`` texts per request.
* **Redacted again before dispatch.** Chunks are already cut from
  ``body_redacted``, but the Slice-1 rule is "redact every text with
  pii.redact() before embedding — no personal data enters the index", so
  this module re-runs it. A ``RedactionError`` aborts: governance fails
  closed, it does not fall back to the raw text.
* **Failure strategy: retry once with backoff, then SKIP the batch.** A
  batch that still fails after the retry is logged at ERROR with its chunk
  ids and dropped from the result. One flaky batch does not crash the run
  and does not corrupt its neighbours. Callers can detect loss by comparing
  ``len(result)`` with ``len(chunks)``; :func:`embed_chunks` also logs the
  shortfall.

Layering (Task 4): imports nothing from ``scout.gmail``,
``scout.connectors`` or ``googleapiclient``.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx
from qdrant_client import QdrantClient, models

from scout.config import settings
from scout.context.chunk import Chunk
from scout.governance import audit
from scout.governance.pii import RedactionError, redact

logger = logging.getLogger(__name__)

# Retry / timeout policy for a transient embedding failure.
RETRY_ATTEMPTS = 2  # initial attempt + one retry, per the docstring above
RETRY_BACKOFF_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 60.0
_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

# TODO(Task 19a): move this to scout.config alongside
# LLM_COST_CEILING_USD_PER_RUN once the reasoning cost-ceiling config lands.
# settings.llm_cost_ceiling_usd_per_run is an OpenRouter *reasoning* ceiling;
# embeddings go direct to OpenAI and are not metered by it. Until a dedicated
# EMBED_COST_CEILING exists we apply the same spirit: estimate before a large
# batch and log — warn, do not hard-stop, because a wrong list price must not
# be able to block ingest.
USD_PER_1M_EMBED_TOKENS = 0.13  # text-embedding-3-large list price, indicative only
COST_ESTIMATE_CHUNK_THRESHOLD = 500  # only bother logging for large runs
_CHARS_PER_TOKEN = 4


class EmbeddingError(RuntimeError):
    """Raised for a non-transient embedding failure that a retry cannot fix."""


@dataclass(frozen=True)
class EmbeddedChunk:
    """A :class:`Chunk` plus its vector.

    ``embedded_text`` is what was actually sent to the embeddings endpoint —
    normally identical to ``chunk.child_text``, but it is recorded separately
    because the defence-in-depth ``pii.redact()`` pass can mask something the
    upstream pass did not.
    """

    chunk: Chunk
    embedding: list[float]
    embedded_text: str
    model: str
    dims: int

    # Pass-through accessors so callers (and the Task 18 index payload) do
    # not have to reach through `.chunk` for the identifiers.
    @property
    def chunk_id(self) -> uuid.UUID:
        return self.chunk.chunk_id

    @property
    def message_id(self) -> Any:
        return self.chunk.message_id

    @property
    def case_id(self) -> Any:
        return self.chunk.case_id

    @property
    def person_id(self) -> Any:
        return self.chunk.person_id

    @property
    def acl_tags(self) -> list[str]:
        return self.chunk.acl_tags

    @property
    def child_text(self) -> str:
        return self.chunk.child_text

    @property
    def parent_text(self) -> str:
        return self.chunk.parent_text

    @property
    def start_offset(self) -> int:
        return self.chunk.start_offset

    @property
    def end_offset(self) -> int:
        return self.chunk.end_offset


# ── Helpers ───────────────────────────────────────────────────────────────


def _batched(items: list[Chunk], size: int) -> Iterable[list[Chunk]]:
    size = max(1, size)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _estimate_cost_usd(texts: list[str]) -> tuple[int, float]:
    tokens = sum(len(text) for text in texts) // _CHARS_PER_TOKEN
    return tokens, tokens / 1_000_000 * USD_PER_1M_EMBED_TOKENS


def _log_cost_estimate(chunks: list[Chunk]) -> None:
    if len(chunks) < COST_ESTIMATE_CHUNK_THRESHOLD:
        return
    tokens, usd = _estimate_cost_usd([c.child_text for c in chunks])
    logger.info(
        "embed_chunks: %d chunks, ~%d tokens, ~$%.4f estimated (model=%s, dims=%d)",
        len(chunks), tokens, usd, settings.embed_model, settings.embed_dims,
    )
    ceiling = getattr(settings, "llm_cost_ceiling_usd_per_run", None)
    if ceiling and usd > ceiling:
        logger.warning(
            "embed_chunks: estimated $%.4f exceeds LLM_COST_CEILING_USD_PER_RUN "
            "($%.2f). Embeddings are not governed by that ceiling yet — see "
            "TODO(Task 19a) in this module.",
            usd, ceiling,
        )


def _redact_for_index(chunks: list[Chunk]) -> list[str]:
    """Second redaction pass. Fails closed — RedactionError is not caught."""
    return [redact(chunk.child_text).text for chunk in chunks]


def _post_embeddings(client: httpx.Client, texts: list[str]) -> list[list[float]]:
    """One embeddings request. Mirrors the OpenAI SDK's embeddings.create shape."""
    response = client.post(
        "/embeddings",
        json={
            "model": settings.embed_model,
            "input": texts,
            "dimensions": settings.embed_dims,
        },
    )
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"embeddings endpoint returned {response.status_code}: {response.text[:500]}",
            request=response.request,
            response=response,
        )

    payload = response.json()
    data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
    if len(data) != len(texts):
        raise EmbeddingError(
            f"embeddings endpoint returned {len(data)} vectors for {len(texts)} inputs."
        )

    vectors = [item["embedding"] for item in data]
    for vector in vectors:
        if len(vector) != settings.embed_dims:
            raise EmbeddingError(
                f"embeddings endpoint returned a {len(vector)}-dim vector, "
                f"expected settings.embed_dims={settings.embed_dims}. The corpus "
                "dimension is pinned — see docs/corpus_datasheet.md."
            )
    return vectors


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def _embed_batch_with_retry(
    client: httpx.Client,
    texts: list[str],
    batch_number: int,
) -> list[list[float]] | None:
    """Return vectors, or None if the batch is being skipped."""
    last_error: BaseException | None = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return _post_embeddings(client, texts)
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            last_error = exc
            if attempt < RETRY_ATTEMPTS and _is_retryable(exc):
                delay = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "embed_chunks: batch %d attempt %d/%d failed (%s) — "
                    "retrying in %.1fs",
                    batch_number, attempt, RETRY_ATTEMPTS, exc, delay,
                )
                time.sleep(delay)
                continue
            break

    logger.error(
        "embed_chunks: batch %d SKIPPED after %d attempt(s) — %s: %s. "
        "These chunks are absent from the result and are not indexed.",
        batch_number, RETRY_ATTEMPTS, type(last_error).__name__, last_error,
    )
    return None


def _client() -> httpx.Client:
    if not settings.openai_api_key:
        raise EmbeddingError(
            "No OpenAI API key configured (settings.openai_api_key / "
            "OPENAI_API_KEY). Embeddings go direct to OpenAI — OpenRouter has "
            "no /embeddings endpoint."
        )
    return httpx.Client(
        base_url=settings.embed_base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _write_audit_rows(embedded: list[EmbeddedChunk]) -> None:
    """One decision_audit row per *message*, not per chunk (audit spam)."""
    per_message: dict[Any, dict[str, Any]] = {}
    for item in embedded:
        entry = per_message.setdefault(
            item.message_id, {"chunk_count": 0, "case_id": item.case_id}
        )
        entry["chunk_count"] += 1

    for message_id, entry in per_message.items():
        case_id = entry["case_id"]
        if isinstance(case_id, str):
            try:
                case_id = uuid.UUID(case_id)
            except ValueError:
                case_id = None
        try:
            audit.write(
                actor="scout.context.embed",
                action="embed_chunks",
                category="system",
                case_id=case_id if isinstance(case_id, uuid.UUID) else None,
                outputs={
                    "chunk_count": entry["chunk_count"],
                    "message_id": str(message_id),
                    "model": settings.embed_model,
                    "dims": settings.embed_dims,
                },
            )
        except Exception as exc:  # noqa: BLE001
            # itr360.decision_audit may not be reachable (no DB in a unit-test
            # or CLI context). Embedding already succeeded; losing the audit
            # row is logged loudly rather than discarding completed work.
            logger.error(
                "embed_chunks: could not write decision_audit row for message "
                "%s — %s: %s",
                message_id, type(exc).__name__, exc,
            )


# ── Public API ────────────────────────────────────────────────────────────


def embed_chunks(chunks: list[Chunk], *, write_audit: bool = True) -> list[EmbeddedChunk]:
    """Embed the ``child_text`` of every chunk.

    Args:
        chunks: chunks from :func:`scout.context.chunk.chunk_message`.
        write_audit: write one ``itr360.decision_audit`` row per message
            processed. Turn off for unit tests with no database.

    Returns:
        One :class:`EmbeddedChunk` per successfully embedded chunk, in input
        order. Chunks whose batch failed twice are **omitted** — the result
        can be shorter than the input. Never partially-correct vectors.

    Raises:
        EmbeddingError: no API key configured.
        RedactionError: the pre-dispatch redaction pass failed (fails closed).
    """
    if not chunks:
        return []

    _log_cost_estimate(chunks)

    embedded: list[EmbeddedChunk] = []
    skipped = 0

    try:
        client = _client()
    except EmbeddingError:
        raise

    with client:
        for batch_number, batch in enumerate(_batched(chunks, settings.embed_batch), start=1):
            try:
                texts = _redact_for_index(batch)
            except RedactionError:
                # Gate one fails closed: never embed text we cannot prove is masked.
                raise

            vectors = _embed_batch_with_retry(client, texts, batch_number)
            if vectors is None:
                skipped += len(batch)
                continue

            for chunk, text, vector in zip(batch, texts, vectors, strict=True):
                embedded.append(
                    EmbeddedChunk(
                        chunk=chunk,
                        embedding=vector,
                        embedded_text=text,
                        model=settings.embed_model,
                        dims=settings.embed_dims,
                    )
                )

    if skipped:
        logger.warning(
            "embed_chunks: %d of %d chunks were skipped after retry and are "
            "NOT indexed.", skipped, len(chunks),
        )

    if write_audit and embedded:
        _write_audit_rows(embedded)

    return embedded


def embed_query(text: str) -> list[float]:
    """Embed a single search string with the same pinned model and dimension.

    Task 18's retrieval leg needs the query in the same vector space as the
    corpus; keeping it here is what stops a second call site drifting onto a
    different model.
    """
    redacted = redact(text).text
    with _client() as client:
        vectors = _embed_batch_with_retry(client, [redacted], batch_number=0)
    if vectors is None:
        raise EmbeddingError("Could not embed query text after retry.")
    return vectors[0]


# ── Index (Task 17, part 3 — the "index" third of "chunk, embed, index") ───
#
# embed_chunks()/embed_query() above produce vectors; the functions below
# put them somewhere Task 18's retrieve.py can actually search. One Qdrant
# collection (settings.qdrant_collection_name), cosine distance, vector
# size = settings.embed_dims — same pinned dimension embed_chunks() already
# enforces, so a corpus embedded here is never silently incompatible with
# what gets indexed.
#
# Layering (Task 4): qdrant-client talks to the Qdrant *infra* container
# (infra/docker-compose.yml, Task 3) over its HTTP API — it is not
# scout.gmail / scout.connectors / googleapiclient, so this import carries
# no layering concern.

_qdrant_client: QdrantClient | None = None


def _get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=settings.qdrant_url)
    return _qdrant_client


def ensure_collection() -> None:
    """Create the Qdrant collection if it doesn't already exist.

    Idempotent and cheap — checks existence first rather than a bare
    create that would error on a second call. Safe to call every time.
    """
    client = _get_qdrant_client()
    if client.collection_exists(settings.qdrant_collection_name):
        return
    client.create_collection(
        collection_name=settings.qdrant_collection_name,
        vectors_config=models.VectorParams(
            size=settings.embed_dims,
            distance=models.Distance.COSINE,
        ),
    )


def _chunk_payload(item: EmbeddedChunk) -> dict[str, Any]:
    """Every field Task 18's trust filter will query against."""
    return {
        "message_id": str(item.message_id) if item.message_id is not None else None,
        "case_id": str(item.case_id) if item.case_id is not None else None,
        "person_id": str(item.person_id) if item.person_id is not None else None,
        "acl_tags": list(item.acl_tags),
        "parent_text": item.parent_text,
        "child_text": item.child_text,
        "start_offset": item.start_offset,
        "end_offset": item.end_offset,
    }


def upsert_chunks(embedded_chunks: list[EmbeddedChunk]) -> None:
    """Write embedded chunks into Qdrant as points, batched in one call.

    Calls :func:`ensure_collection` first (idempotent, cheap) so callers
    never have to remember to set the collection up themselves.
    """
    if not embedded_chunks:
        return

    ensure_collection()

    points = [
        models.PointStruct(
            id=str(item.chunk_id),
            vector=item.embedding,
            payload=_chunk_payload(item),
        )
        for item in embedded_chunks
    ]

    client = _get_qdrant_client()
    client.upsert(collection_name=settings.qdrant_collection_name, points=points)


_SHOULD_KEY = "$should"


def _field_conditions(fields: dict[str, Any]) -> list[models.FieldCondition]:
    """{field: value_or_list} -> FieldConditions. List -> MatchAny, scalar -> MatchValue."""
    conditions: list[models.FieldCondition] = []
    for key, value in fields.items():
        if isinstance(value, (list, tuple, set)):
            conditions.append(models.FieldCondition(key=key, match=models.MatchAny(any=list(value))))
        else:
            conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
    return conditions


def _build_acl_filter(acl_filter: dict[str, Any] | None) -> models.Filter | None:
    """Build a Qdrant payload filter from a simple {field: value(s)} dict.

    A list value matches any of its members (MatchAny); a scalar value
    matches exactly (MatchValue). All top-level keys are ANDed (``must``).

    One extension, for the KB pipeline: the reserved key ``"$should"`` may
    carry a list of {field: value(s)} dicts. Each dict becomes one
    ``must`` group, and the groups are ORed together under Qdrant's
    ``should`` — i.e. ``(A) OR (B)``, ANDed with the top-level ``must``.
    retrieve.py uses this to express "this case's chunks OR any
    tenant-wide KB article". Task 18 owns any richer trust logic — this
    is still a direct translation, nothing more.
    """
    if not acl_filter:
        return None

    plain = {k: v for k, v in acl_filter.items() if k != _SHOULD_KEY}
    should_groups = acl_filter.get(_SHOULD_KEY) or []

    must = _field_conditions(plain)
    should = [
        models.Filter(must=_field_conditions(group))
        for group in should_groups
        if group
    ]

    if not must and not should:
        return None
    return models.Filter(must=must or None, should=should or None)


def search(
    query_embedding: list[float],
    top_k: int,
    acl_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Vector search against the collection.

    Thin, direct wrapper — no ranking logic beyond what Qdrant itself
    does. Task 18 owns any further trust/relevance filtering. Returns a
    list of dicts, each carrying at least chunk_id, score, and payload.
    """
    client = _get_qdrant_client()
    response = client.query_points(
        collection_name=settings.qdrant_collection_name,
        query=query_embedding,
        limit=top_k,
        query_filter=_build_acl_filter(acl_filter),
        with_payload=True,
    )

    return [
        {
            "chunk_id": point.id,
            "score": point.score,
            "payload": point.payload,
        }
        for point in response.points
    ]


def collection_stats() -> dict[str, Any]:
    """Point count and basic status — what the console's Knowledge Layer
    card will eventually display."""
    client = _get_qdrant_client()
    info = client.get_collection(settings.qdrant_collection_name)
    return {
        "name": settings.qdrant_collection_name,
        "points_count": info.points_count,
        "status": info.status,
    }


__all__ = [
    "Chunk",
    "EmbeddedChunk",
    "EmbeddingError",
    "embed_chunks",
    "embed_query",
    "ensure_collection",
    "upsert_chunks",
    "search",
    "collection_stats",
]
