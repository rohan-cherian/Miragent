"""Corpus aggregates for Scene 1 — live counts from ``src_zendesk``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scout.service.db import Database

# Mapping for the console Scene 1 tile:
#   tickets   → src_zendesk.tickets
#   accounts  → organizations (customer accounts)
#   analysts  → agent + admin users
#   channels  → distinct ticket via_channel values (web, email, …)
_CORPUS_STATS_SQL = """
SELECT
    (SELECT COUNT(*) FROM src_zendesk.tickets) AS tickets,
    (SELECT COUNT(*) FROM src_zendesk.organizations) AS accounts,
    (
        SELECT COUNT(*)
        FROM src_zendesk.users
        WHERE role IN ('agent', 'admin')
    ) AS analysts,
    (
        SELECT COUNT(DISTINCT via_channel)
        FROM src_zendesk.tickets
        WHERE via_channel IS NOT NULL
    ) AS channels,
    (SELECT MIN(created_at) FROM src_zendesk.tickets) AS date_start,
    (
        SELECT MAX(COALESCE(updated_at, created_at))
        FROM src_zendesk.tickets
    ) AS date_end
"""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat() + "Z"
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def fetch_corpus_stats(db: Database) -> dict[str, Any]:
    """Return live corpus aggregates — never stubs."""
    row = db.fetch_one(_CORPUS_STATS_SQL)
    return {
        "tickets": int(row["tickets"] or 0),
        "accounts": int(row["accounts"] or 0),
        "analysts": int(row["analysts"] or 0),
        "channels": int(row["channels"] or 0),
        "date_range": {
            "start": _iso(row["date_start"]),
            "end": _iso(row["date_end"]),
        },
    }
