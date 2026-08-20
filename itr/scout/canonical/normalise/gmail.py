"""
Task 13 — normalise a src_gmail.message row into a canonical
itr360.message row.

Pure transform: reads nothing, writes nothing, has no idea how the
source row got into the database or how the canonical row gets
persisted (scripts/ingest_canonical.py owns both of those). This
module must never import scout.gmail, scout.connectors, or
googleapiclient — that's the whole point of the layering rule Task 4
enforces (tests/test_layering.py). It only ever sees rows handed to
it, shaped like src_gmail.message.

Column names CONFIRMED against schema/003_src_gmail_regrain.sql
(Rohan's Task 5, now merged): external_id (the Gmail messageId —
"= DEDUP KEY" per the schema comment), thread_id (uuid FK into
src_gmail.thread — an internal stable identifier, NOT Gmail's
threadId string, which lives at thread.external_id), subject,
body_text, internal_date_ms, connector_run_id, from_address /
from_display_name / signature_block (read by Task 14's waterfall,
not here).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from scout.config import settings
from scout.governance.pii import redact_and_audit

SOURCE_SYSTEM = "gmail"

# itr360.message column -> src_gmail.message column.
# This is the thing a future Zendesk-adapter author reads and copies —
# every direct field correspondence lives here, never as inline
# if/elif comparisons in normalise_message() below.
FIELD_MAP: dict[str, str] = {
    "src_message_id": "external_id",  # the Gmail messageId — schema/003's dedup key
    "subject": "subject",
}
# thread_id is NOT in FIELD_MAP: the source value is a uuid (FK into
# src_gmail.thread) while itr360.message.thread_id is Text, so it is a
# CONVERTED field (str-cast) in the update block below, like sent_at.
# Using the internal thread uuid as the correlation grouping key is
# deliberate: Task 15 needs a stable per-thread key, not Gmail's literal
# threadId string — and the uuid is stable by construction (documented
# decision; join to src_gmail.thread.external_id only if a future
# consumer needs the literal Gmail value).

# Canonical columns NOT covered by FIELD_MAP, and why:
#   body_redacted / pii_map / pii_status  -> derived from redact(body_text), not a direct copy
#   sent_at                                -> internal_date_ms (epoch ms) -> tz-aware UTC datetime
#   direction / channel                    -> constants for now: inbound / email. Gmail sync only
#                                              ever produces customer-initiated messages by
#                                              construction (Task 5 filters to customer senders
#                                              before rows land in src_gmail.message).
#   person_id                              -> Task 14: identity resolution goes here
#   case_id                                -> Task 15: case correlation goes here
#   tenant_id / source_system / external_id/
#   is_synthetic / connector_run_id /
#   observed_at / valid_from               -> Provenance. Has its own rules (see below), not a
#                                              generic vendor-field copy.


def normalise_message(src_row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one src_gmail.message row into a canonical itr360.message-shaped dict.

    Pure transform — no DB reads, no DB writes, and no `id` in the
    returned dict (the persistence layer decides whether that's a
    fresh id or an existing row's id). Raises RedactionError if
    redact() cannot guarantee the body is safely masked; every other
    field-shape problem in `src_row` (missing/renamed column) raises
    naturally as a KeyError for the caller to handle per-record.
    """
    body_text = src_row.get("body_text") or ""
    # The audited redaction path (gate one now leaves an audit row).
    # case_id=None is correct here: redaction structurally precedes case
    # correlation — see redact_and_audit()'s docstring.
    redaction = redact_and_audit(body_text, source="gmail_normalise", case_id=None)

    internal_date_ms = src_row["internal_date_ms"]
    sent_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=UTC)

    now = datetime.now(UTC)
    source_message_id = src_row["external_id"]

    canonical: dict[str, Any] = {
        field: src_row[source_field] for field, source_field in FIELD_MAP.items()
    }

    canonical.update(
        {
            "case_id": None,  # Task 15: case correlation goes here
            "person_id": None,  # Task 14: identity resolution goes here
            "direction": "inbound",
            "channel": "email",
            "body_redacted": redaction.text,
            "pii_map": redaction.pii_map,
            "pii_status": redaction.status,
            "sent_at": sent_at,
            "thread_id": (
                str(src_row["thread_id"]) if src_row.get("thread_id") else None
            ),
            "tenant_id": uuid.UUID(str(settings.tenant_id)),
            "source_system": SOURCE_SYSTEM,
            "external_id": str(source_message_id),
            "is_synthetic": bool(src_row.get("is_synthetic", False)),
            "connector_run_id": src_row["connector_run_id"],  # carried through unchanged
            "observed_at": now,
            "valid_from": now,
        }
    )

    return canonical
