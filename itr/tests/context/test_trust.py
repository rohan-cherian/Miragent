"""
Task 18, Part 4 — tests for scout.context.trust.trust_filter().

Pure unit tests: hit dicts are fed directly, no Qdrant needed. Each
test targets exactly one branch of the two-check pipeline (relevance
floor, then ACL) plus the fail-closed contract.
"""

from __future__ import annotations

import uuid

import pytest

from scout.config import settings
from scout.context import trust as trust_module
from scout.context.trust import trust_filter

TENANT_A = f"tenant:{uuid.uuid4()}"
TENANT_B = f"tenant:{uuid.uuid4()}"
ORG_A = f"org:{uuid.uuid4()}"
ORG_B = f"org:{uuid.uuid4()}"


def _hit(score: float, acl_tags: list[str], chunk_id: str | None = None) -> dict:
    return {
        "chunk_id": chunk_id or str(uuid.uuid4()),
        "score": score,
        "payload": {
            "message_id": str(uuid.uuid4()),
            "acl_tags": acl_tags,
            "parent_text": "parent text",
            "child_text": "child text",
        },
    }


def test_below_floor_chunk_is_dropped():
    below = settings.retrieval_floor - 0.01
    hit = _hit(score=below, acl_tags=[TENANT_A])

    result = trust_filter([hit], acl_tags=[TENANT_A])

    assert result == []


def test_non_overlapping_acl_tags_returned_marked_restricted_not_dropped():
    hit = _hit(score=0.99, acl_tags=[TENANT_B])

    result = trust_filter([hit], acl_tags=[TENANT_A])

    assert len(result) == 1
    assert result[0]["access_status"] == "restricted"
    assert result[0]["payload"]["child_text"] is None
    assert result[0]["payload"]["parent_text"] is None


def test_tenant_wide_chunk_with_no_org_tag_passes_for_any_caller_in_tenant():
    hit = _hit(score=0.99, acl_tags=[TENANT_A])  # no org: tag -> tenant-wide

    result = trust_filter([hit], acl_tags=[TENANT_A, ORG_B])

    assert len(result) == 1
    assert result[0]["access_status"] == "ok"


def test_matching_tags_and_score_above_floor_passes_with_ok_status():
    hit = _hit(score=0.99, acl_tags=[TENANT_A, ORG_A])

    result = trust_filter([hit], acl_tags=[TENANT_A, ORG_A])

    assert len(result) == 1
    assert result[0]["access_status"] == "ok"
    assert result[0]["payload"]["child_text"] == "child text"


def test_org_tag_mismatch_within_same_tenant_is_restricted():
    hit = _hit(score=0.99, acl_tags=[TENANT_A, ORG_A])

    result = trust_filter([hit], acl_tags=[TENANT_A, ORG_B])

    assert len(result) == 1
    assert result[0]["access_status"] == "restricted"


def test_internal_error_fails_closed_to_empty_list_and_does_not_raise(monkeypatch):
    hit = _hit(score=0.99, acl_tags=[TENANT_A])

    def _boom(*args, **kwargs):
        raise RuntimeError("audit backend unreachable")

    monkeypatch.setattr(trust_module.audit, "write", _boom)

    result = trust_filter([hit], acl_tags=[TENANT_A])

    assert result == []
