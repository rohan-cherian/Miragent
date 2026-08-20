"""
Task 18, Part 3 — compile(): assemble the ContextPack.

Sequence: retrieve() once -> trust_filter() (owns the relevance floor
and the ACL gate) -> compress the surviving 'ok' hits to token_budget,
dropping whole citations rather than truncating one. A citation that
survives into a ContextPack is always exactly what its source chunk
said — that is what lets a later drafting step refuse to make an
uncitable claim.

Citation.source_ts isn't carried in the Qdrant chunk payload (Task 17's
payload has no timestamp field) — this module looks it up with a
single batched, read-only SQLAlchemy query against itr360.message.
sent_at by message_id. scout/canonical/ itself is not modified; this
only reads scout.canonical.models, which is layering-legal (it is not
in tests/test_layering.py's FORBIDDEN_IMPORTS).

Must never import scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical.models import KBArticle, Message
from scout.config import settings
from scout.context.retrieve import retrieve
from scout.context.trust import trust_filter

# Slice 1 is Gmail-only, so this is hardcoded locally rather than imported
# from scout.canonical.normalise.gmail — this task's do-not-touch list
# names the whole scout/canonical/ directory, so new imports from it are
# kept to the one genuinely needed (Message, for the source_ts lookup).
_SOURCE_SYSTEM = "gmail"
# Closest fit in the OpenAPI source_type enum (ticket | comment | article |
# resolution | graph_path) — there is no "email" option, and a customer
# email in this system is conceptually a ticket comment. Documented here
# since the spec doesn't pin this mapping down.
_SOURCE_TYPE = "comment"

# KB articles (scout/context/kb_index.py) are indexed into the same
# collection with payload["source_system"] == "kb_article". They are the
# one case where the OpenAPI source_type enum has an exact fit: "article".
_KB_SOURCE_SYSTEM = "kb_article"
_KB_SOURCE_TYPE = "article"

# Mirrors embed.py's own private token-estimate convention (chars / 4);
# redefined locally since embed.py's constant isn't exported and Part 3
# doesn't touch embed.py.
_CHARS_PER_TOKEN = 4

# Fallback for Citation.to_dto() when source_ts is None (see the comment
# there). openapi/console-api-v1.yaml's Citation.source_ts is a required,
# non-nullable `type: string, format: date-time` — there is no null the
# wire format can carry, so a fixed, recognisable sentinel stands in.
_MISSING_SOURCE_TS_SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _lookup_kb_observed_at(article_ids: set[str]) -> dict[str, datetime]:
    """Batched, read-only lookup of itr360.kb_article.observed_at by id.

    KB points carry the article id in payload["kb_article_id"] (and, for
    payload-shape compatibility, in payload["message_id"] too — see
    kb_index.py). Their timestamp lives on kb_article, not itr360.message,
    so they are resolved here rather than in _lookup_sent_at.
    """
    if not article_ids:
        return {}

    parsed_ids: list[uuid.UUID] = []
    for aid in article_ids:
        try:
            parsed_ids.append(uuid.UUID(str(aid)))
        except (ValueError, TypeError):
            continue
    if not parsed_ids:
        return {}

    engine = _get_engine()
    with Session(engine) as session:
        rows = session.execute(
            select(KBArticle.id, KBArticle.observed_at).where(KBArticle.id.in_(parsed_ids))
        ).all()
    return {str(row.id): row.observed_at for row in rows}


def _is_kb_hit(hit: dict) -> bool:
    return ((hit.get("payload") or {}).get("source_system")) == _KB_SOURCE_SYSTEM


def _kb_article_id(hit: dict) -> str | None:
    payload = hit.get("payload") or {}
    return payload.get("kb_article_id") or payload.get("message_id")


def _lookup_sent_at(message_ids: set[str]) -> dict[str, datetime]:
    """Batched, read-only lookup of itr360.message.sent_at by id."""
    if not message_ids:
        return {}

    parsed_ids: list[uuid.UUID] = []
    for mid in message_ids:
        try:
            parsed_ids.append(uuid.UUID(str(mid)))
        except (ValueError, TypeError):
            continue
    if not parsed_ids:
        return {}

    engine = _get_engine()
    with Session(engine) as session:
        rows = session.execute(
            select(Message.id, Message.sent_at).where(Message.id.in_(parsed_ids))
        ).all()
    return {str(row.id): row.sent_at for row in rows}


@dataclass
class Citation:
    """Internal citation. to_dto() emits the exact wire shape from
    openapi/console-api-v1.yaml's Citation schema."""

    # wire, required
    source_system: str
    source_type: str
    object_id: str
    excerpt: str
    source_ts: datetime
    deep_link: str
    access_status: str  # "ok" | "restricted" | "missing"
    # wire, optional
    relevance: float | None = None
    # internal, extra — not part of the wire DTO
    chunk_id: str | None = None
    message_id: str | None = None
    parent_text: str | None = None
    child_text: str | None = None
    score: float | None = None

    def to_dto(self) -> dict[str, Any]:
        source_ts = self.source_ts
        access_status = self.access_status
        if source_ts is None:
            # Orphaned chunk: its message_id doesn't resolve to a live
            # itr360.message row (_lookup_sent_at() found nothing for it —
            # e.g. the message was deleted or reprocessed after the chunk
            # was indexed), so there is no real timestamp to report. The
            # wire schema won't take null here, so fall back to a fixed
            # sentinel and force access_status to "missing" — the same
            # signal a caller would otherwise have to reconstruct itself
            # after catching the AttributeError this used to raise.
            source_ts = _MISSING_SOURCE_TS_SENTINEL
            access_status = "missing"

        dto: dict[str, Any] = {
            "source_system": self.source_system,
            "source_type": self.source_type,
            "object_id": self.object_id,
            "excerpt": self.excerpt,
            "source_ts": source_ts.isoformat(),
            "deep_link": self.deep_link,
            "access_status": access_status,
        }
        if self.relevance is not None:
            dto["relevance"] = self.relevance
        return dto


@dataclass
class ContextPack:
    case_id: uuid.UUID
    citations: list[Citation]
    low_context: bool
    token_count: int
    citation_coverage: float
    compile_ms: float
    trust_filtered: bool


def _to_citation(
    hit: dict,
    sent_at_by_message_id: dict[str, datetime],
    observed_at_by_kb_article_id: dict[str, datetime] | None = None,
) -> Citation:
    payload = hit.get("payload") or {}
    message_id = payload.get("message_id")
    child_text = payload.get("child_text") or ""

    if _is_kb_hit(hit):
        # KB article: timestamp from itr360.kb_article, source_type "article",
        # deep link into the KB rather than Gmail. Everything else is shared.
        article_id = _kb_article_id(hit)
        source_ts = (observed_at_by_kb_article_id or {}).get(str(article_id)) if article_id else None
        source_system = _KB_SOURCE_SYSTEM
        source_type = _KB_SOURCE_TYPE
        deep_link = f"kb://article/{article_id}" if article_id else ""
    else:
        source_ts = sent_at_by_message_id.get(str(message_id)) if message_id else None
        source_system = _SOURCE_SYSTEM
        source_type = _SOURCE_TYPE
        deep_link = f"https://mail.google.com/mail/u/0/#all/{message_id}" if message_id else ""

    return Citation(
        source_system=source_system,
        source_type=source_type,
        object_id=str(message_id) if message_id else str(hit.get("chunk_id")),
        excerpt=child_text,
        source_ts=source_ts,
        deep_link=deep_link,
        access_status=hit.get("access_status", "ok"),
        relevance=hit.get("score"),
        chunk_id=hit.get("chunk_id"),
        message_id=message_id,
        parent_text=payload.get("parent_text"),
        child_text=child_text,
        score=hit.get("score"),
    )


def compile(
    intent: str,
    case_id: uuid.UUID,
    query_text: str,
    acl_tags: list[str],
) -> ContextPack:
    """Assemble a ContextPack: retrieve once, trust-filter, compress to
    budget. intent is accepted but unused in Slice 1 — a single fixed
    settings.token_budget applies to every intent; a per-intent policy
    table is a later-slice concern and this signature won't need to
    change when it lands.
    """
    start = time.monotonic()
    budget = settings.token_budget

    hits = retrieve(query_text, case_id, acl_tags, top_k=20)

    # trust_filter() owns the relevance floor (settings.retrieval_floor) —
    # it is not re-applied here. Two call sites defining one threshold is
    # how they drift.
    filtered = trust_filter(hits, acl_tags)

    ok_hits = [h for h in filtered if h.get("access_status") == "ok"]
    ok_hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)

    # Email hits resolve their timestamp from itr360.message; KB hits from
    # itr360.kb_article. Split by payload["source_system"] so an article id
    # is never looked up against the message table (and vice versa).
    message_ids = {
        str(h["payload"]["message_id"])
        for h in ok_hits
        if not _is_kb_hit(h) and (h.get("payload") or {}).get("message_id")
    }
    kb_article_ids = {
        str(_kb_article_id(h)) for h in ok_hits if _is_kb_hit(h) and _kb_article_id(h)
    }
    sent_at_by_message_id = _lookup_sent_at(message_ids)
    observed_at_by_kb_article_id = _lookup_kb_observed_at(kb_article_ids)

    citations: list[Citation] = []
    token_count = 0
    for hit in ok_hits:
        citation = _to_citation(hit, sent_at_by_message_id, observed_at_by_kb_article_id)
        citation_tokens = _estimate_tokens(citation.excerpt)
        if token_count + citation_tokens > budget:
            break  # next citation would exceed budget — stop, never truncate
        citations.append(citation)
        token_count += citation_tokens

    compile_ms = (time.monotonic() - start) * 1000

    low_context = len(citations) == 0
    citation_coverage = (len(citations) / len(ok_hits)) if ok_hits else 1.0
    trust_filtered = any(h.get("access_status") == "restricted" for h in filtered)

    return ContextPack(
        case_id=case_id,
        citations=citations,
        low_context=low_context,
        token_count=token_count,
        citation_coverage=citation_coverage,
        compile_ms=compile_ms,
        trust_filtered=trust_filtered,
    )


__all__ = ["Citation", "ContextPack", "compile"]
