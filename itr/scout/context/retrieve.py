"""
Task 18, Part 1 — retrieve(): the vector-only retrieval leg.

Slice 1 retrieval is vector-only — no BM25 leg, no graph leg, no
reranker. This module's public surface is deliberately just
retrieve() so Slice 3 can add legs (BM25, graph) without any caller
changing.

This is a seam, not a stage: retrieve() returns raw hits — chunk_id,
score, payload — with no ranking, filtering, or scoring logic of its
own. scout.context.trust and scout.context.compile own everything
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


def _build_acl_filter(
    acl_tags: list[str] | None, case_id: uuid.UUID | None
) -> dict[str, Any] | None:
    """{field: value_or_list} shape search() expects — a list value becomes
    MatchAny, a scalar becomes MatchValue (see embed.py's _build_acl_filter)."""
    filter_dict: dict[str, Any] = {}
    if acl_tags:
        filter_dict["acl_tags"] = list(acl_tags)
    if case_id is not None:
        filter_dict["case_id"] = str(case_id)
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
