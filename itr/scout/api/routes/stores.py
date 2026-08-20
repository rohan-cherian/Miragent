"""
Task 24 — GET /stores/metrics.

The console's Knowledge Layer panel. The doc is specific about the shape:

  * Postgres  — live row counts per canonical table
  * Qdrant    — point count, with the vector dimension and model name
  * Neo4j     — null, with a "not_indexed_until_slice_3" note

Neo4j reports null rather than a zero on purpose. A zero reads as "the graph
is empty"; null plus a note reads as "the graph is not built yet", which is
the truth in Slice 1. Inventing a plausible number is the one thing this
endpoint must not do.

Counts are read live, never cached — the panel exists to show what is actually
in the stores right now.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors, or
googleapiclient.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from scout.api.deps import get_db_session
from scout.config import settings

router = APIRouter()

# The canonical tables the console reports on, in the order it shows them.
_CANONICAL_TABLES = (
    "org",
    "person",
    "case_",
    "message",
    "kb_article",
    "proposed_action",
    "recommendation_decision",
    "write_execution",
    "triage_result",
    "decision_audit",
    "identity_unresolved_queue",
)


def _postgres_counts(session: Session) -> dict[str, int]:
    """Live row count per canonical table.

    One UNION ALL rather than a query per table: eleven round trips on a panel
    that refreshes is wasteful, and the counts should be from one moment
    rather than eleven.
    """
    union = " UNION ALL ".join(
        f"SELECT '{t}' AS table_name, count(*) AS n FROM itr360.{t}"
        for t in _CANONICAL_TABLES
    )
    rows = session.execute(text(union)).mappings().all()
    return {row["table_name"]: int(row["n"]) for row in rows}


def _qdrant_metrics() -> dict[str, Any]:
    """Point count plus the pins that decide whether a re-embed is needed.

    Unreachable Qdrant reports an error string rather than zero, for the same
    reason Neo4j reports null: "we could not ask" and "there is nothing there"
    are different answers and the console should not conflate them.
    """
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.qdrant_url, timeout=3)
        collections = [c.name for c in client.get_collections().collections]
        points = 0
        for name in collections:
            points += int(client.count(collection_name=name, exact=True).count)
        return {
            "points": points,
            "collections": collections,
            "dimension": settings.embed_dims,
            "model": settings.embed_model,
            "url": settings.qdrant_url,
        }
    except Exception as exc:
        return {
            "points": None,
            "collections": [],
            "dimension": settings.embed_dims,
            "model": settings.embed_model,
            "url": settings.qdrant_url,
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.get("/stores/metrics")
def stores_metrics(session: Session = Depends(get_db_session)) -> Any:
    counts = _postgres_counts(session)
    return {
        "postgres": {
            "tables": counts,
            "total_rows": sum(counts.values()),
        },
        "qdrant": _qdrant_metrics(),
        # Deliberately null, not zero. Slice 3 builds the graph.
        "neo4j": None,
        "neo4j_note": "not_indexed_until_slice_3",
    }
