"""
Task 18, Part 1 — retrieve(): the vector-only retrieval leg.

Slice 1 retrieval is vector-only — no BM25 leg, no graph leg, no
reranker. This module's public surface is deliberately just
retrieve() so Slice 3 can add legs (BM25, graph) without any caller
changing.

This is a seam, not a stage: retrieve() returns raw hits — chunk_id,
score, payload — with no ranking, filtering, or scoring logic of its
own. The one piece of query-shape logic it owns is the case-OR-KB
scoping in _build_acl_filter, so that tenant-wide KB articles are
retrievable alongside a case's own messages. scout.context.trust and scout.context.compile own everything
downstream of the vector search itself.

scout.context.embed.search() takes a query VECTOR (list[float]), not
a query string — confirmed by reading its signature before writing
this module. So retrieve() calls embed_query() exactly once itself;
nothing downstream embeds again (embedding twice would double the
per-compile latency and cost).

Must never import scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import uuid
from typing import Any

from scout.context.embed import embed_query, search

# Payload value written by scout/context/kb_index.py for every KB point.
# Kept in sync by tests/context/test_kb_index.py.
KB_SOURCE_SYSTEM = "kb_article"


def _tenant_tags(acl_tags: list[str] | None) -> list[str]:
    return [tag for tag in (acl_tags or []) if tag.startswith("tenant:")]


def _build_acl_filter(
    acl_tags: list[str] | None, case_id: uuid.UUID | None
) -> dict[str, Any] | None:
    """{field: value_or_list} shape search() expects — a list value becomes
    MatchAny, a scalar becomes MatchValue (see embed.py's _build_acl_filter).

    Case scoping is an OR, not a hard AND:

        acl_tags match
        AND ( case_id == <this case>
              OR ( source_system == "kb_article" AND acl_tags match tenant ) )

    Email chunks carry a case_id; KB article chunks carry case_id=None and
    are tenant-wide. A bare ``case_id`` MatchValue would exclude every KB
    point server-side, which is exactly what happened before this change —
    the KB index was unreachable from any real compile() call. Expressed via
    embed._build_acl_filter's ``"$should"`` key.
    """
    filter_dict: dict[str, Any] = {}
    if acl_tags:
        filter_dict["acl_tags"] = list(acl_tags)

    if case_id is not None:
        kb_group: dict[str, Any] = {"source_system": KB_SOURCE_SYSTEM}
        tenant_tags = _tenant_tags(acl_tags)
        if tenant_tags:
            kb_group["acl_tags"] = tenant_tags
        filter_dict["$should"] = [
            {"case_id": str(case_id)},
            kb_group,
        ]

    return filter_dict or None


def retrieve(
    query_text: str,
    case_id: uuid.UUID | None,
    acl_tags: list[str] | None,
    top_k: int = 20,
) -> list[dict]:
    """Embed query_text once, then vector-search the index.

    Returns raw hits exactly as embed.search() returns them — no
    ranking, filtering, or scoring beyond what Qdrant itself does.
    """
    query_embedding = embed_query(query_text)
    acl_filter = _build_acl_filter(acl_tags, case_id)
    return search(query_embedding=query_embedding, top_k=top_k, acl_filter=acl_filter)


__all__ = ["retrieve"]
