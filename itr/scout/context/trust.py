"""
Task 18, Part 2 — trust_filter(): governance gate two.

Gate one was Task 12's redaction. This is gate two: the pack is
ACL-filtered before it exists, not before it is displayed — a hard
gate, not a display-time convenience.

Fails closed to empty: on ANY internal error in the FILTERING logic
(malformed payload, missing acl_tags key, exception anywhere in the
ACL check), this returns [] — never the unfiltered input. An empty
pack is a safe, valid state (the caller gets low_context=True);
leaking one unfiltered chunk is not.

The audit write is a SEPARATE failure domain. It happens after the
filtering result already exists, in its own guarded block: an
audit-logging failure (a transient decision_audit hiccup) is logged
as a warning and never changes what this function returns. A logging
failure and a governance failure are two different things — coupling
them meant a flaky audit table silently degraded every context pack
to low_context with no data-safety reason.

Must never import scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import logging
from typing import Any

from scout.config import settings
from scout.governance import audit

logger = logging.getLogger(__name__)


def _acl_allows(chunk_acl_tags: list[str], caller_acl_tags: list[str]) -> bool:
    """ACL rule (not pinned down by the spec — documented here):

    - The chunk's stored tenant: tag must match one of the caller's
      tenant: tags exactly.
    - If the chunk also carries an org: tag, at least one of the
      caller's org: tags must match one of the chunk's org: tags.
    - A chunk with no org: tag at all is tenant-wide and passes for
      any caller in that tenant (once the tenant: tag matches).
    - A chunk with no tenant: tag at all can never match — every
      chunk in Slice 1 belongs to some tenant.
    """
    caller_tenants = {tag for tag in caller_acl_tags if tag.startswith("tenant:")}
    caller_orgs = {tag for tag in caller_acl_tags if tag.startswith("org:")}

    chunk_tenants = [tag for tag in chunk_acl_tags if tag.startswith("tenant:")]
    chunk_orgs = [tag for tag in chunk_acl_tags if tag.startswith("org:")]

    if not chunk_tenants:
        return False
    if not any(tag in caller_tenants for tag in chunk_tenants):
        return False

    if not chunk_orgs:
        return True

    return any(tag in caller_orgs for tag in chunk_orgs)


def trust_filter(retrieved_chunks: list[dict], acl_tags: list[str]) -> list[dict]:
    """Governance gate two. Fails closed to [] on ANY internal error.

    Order of checks, cheapest first:
      1. score < settings.retrieval_floor -> dropped silently. Ordinary
         relevance filtering — nothing was withheld from the caller.
      2. ACL check -> non-matching hits are MARKED
         access_status='restricted' (excerpt withheld) rather than
         dropped, so the console can render "evidence unavailable".
         Matching hits get access_status='ok'.

    These two rejection reasons stay distinguishable in the output:
    below-floor hits never appear at all; ACL-restricted hits appear,
    marked and excerpt-withheld.
    """
    input_count = len(retrieved_chunks)
    restricted_count = 0
    failed = False

    # ── Failure domain 1: the governance check itself. Fails closed. ──────
    try:
        output: list[dict] = []

        for hit in retrieved_chunks:
            score = hit["score"]
            if score < settings.retrieval_floor:
                continue

            payload = hit.get("payload") or {}
            chunk_acl_tags = payload.get("acl_tags")
            if chunk_acl_tags is None:
                raise KeyError("payload missing acl_tags")

            if _acl_allows(chunk_acl_tags, acl_tags):
                marked = dict(hit)
                marked["access_status"] = "ok"
                output.append(marked)
            else:
                restricted_count += 1
                marked = dict(hit)
                marked["access_status"] = "restricted"
                marked_payload = dict(payload)
                marked_payload["parent_text"] = None
                marked_payload["child_text"] = None
                marked["payload"] = marked_payload
                output.append(marked)

    except Exception:
        # Task 18 spec: "it must log and return an empty list".
        logger.exception(
            "trust_filter: filtering failed — failing closed to an empty "
            "list (%d hit(s) suppressed).", input_count,
        )
        output = []
        restricted_count = 0
        failed = True

    # ── Failure domain 2: the audit row. Never changes the return value. ──
    outputs: dict[str, Any] = {
        "input_count": input_count,
        "output_count": len(output),
        "restricted_count": restricted_count,
    }
    if failed:
        outputs["failed_closed"] = True
    try:
        audit.write(
            actor="scout.context.trust",
            action="trust_filter",
            category="system",
            outputs=outputs,
        )
    except Exception as exc:  # noqa: BLE001 — logging failure must not cascade
        logger.warning(
            "trust_filter: audit row could not be written (%s: %s) — "
            "returning the computed filtering result regardless.",
            type(exc).__name__, exc,
        )

    return output


__all__ = ["trust_filter"]
