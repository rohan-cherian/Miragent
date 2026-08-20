"""
Task 18, Part 4 — tests for scout.context.trust.trust_filter().

Pure unit tests: hit dicts are fed directly, no Qdrant needed. Each
test targets exactly one branch of the two-check pipeline (relevance
floor, then ACL) plus the fail-closed contract.
"""

from __future__ import annotations

import uuid

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
    """A failure in the FILTERING logic itself fails closed to []."""
    hit = _hit(score=0.99, acl_tags=[TENANT_A])

    def _boom(*args, **kwargs):
        raise RuntimeError("ACL check exploded")

    monkeypatch.setattr(trust_module, "_acl_allows", _boom)
    monkeypatch.setattr(trust_module.audit, "write", lambda **kw: None)

    result = trust_filter([hit], acl_tags=[TENANT_A])

    assert result == []


def test_malformed_payload_fails_closed_to_empty_list(monkeypatch, caplog):
    """The concrete malformed-input vector: a payload with no acl_tags key
    raises inside the filtering block -> fail closed, and (per the Task 18
    spec) the failure is logged."""
    monkeypatch.setattr(trust_module.audit, "write", lambda **kw: None)
    good = _hit(score=0.99, acl_tags=[TENANT_A])
    bad = _hit(score=0.99, acl_tags=[TENANT_A])
    bad["payload"] = {"message_id": bad["payload"]["message_id"]}  # no acl_tags

    with caplog.at_level("ERROR"):
        result = trust_filter([good, bad], acl_tags=[TENANT_A])

    assert result == [], "one malformed hit poisons the batch — never a partial leak"
    assert any("failing closed" in record.message for record in caplog.records)


def test_audit_write_failure_does_not_discard_valid_filtering_results(monkeypatch, caplog):
    """THE decoupling fix: an audit-logging failure is not a governance
    failure. The correctly-filtered results are returned anyway, with a
    warning — never [] (the old behaviour this test replaces)."""
    hit = _hit(score=0.99, acl_tags=[TENANT_A])

    def _boom(*args, **kwargs):
        raise RuntimeError("audit backend unreachable")

    monkeypatch.setattr(trust_module.audit, "write", _boom)

    with caplog.at_level("WARNING"):
        result = trust_filter([hit], acl_tags=[TENANT_A])

    assert len(result) == 1, "valid filtering output must survive an audit hiccup"
    assert result[0]["access_status"] == "ok"
    assert any("audit row could not be written" in record.message for record in caplog.records)


def test_fail_closed_path_still_attempts_an_audit_row(monkeypatch):
    """When filtering fails closed, an audit row noting the failure is still
    attempted — and its own failure cannot cascade (return stays [])."""
    written: list[dict] = []
    monkeypatch.setattr(trust_module, "_acl_allows",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(trust_module.audit, "write", lambda **kw: written.append(kw))

    hit = _hit(score=0.99, acl_tags=[TENANT_A])
    assert trust_filter([hit], acl_tags=[TENANT_A]) == []
    assert written and written[0]["outputs"]["failed_closed"] is True
    assert written[0]["outputs"]["output_count"] == 0

    # ...and even if THAT audit write raises too, the return is still [].
    monkeypatch.setattr(trust_module.audit, "write",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("also down")))
    assert trust_filter([hit], acl_tags=[TENANT_A]) == []


def test_happy_path_writes_one_audit_row_with_counts(monkeypatch):
    written: list[dict] = []
    monkeypatch.setattr(trust_module.audit, "write", lambda **kw: written.append(kw))

    hits = [
        _hit(score=0.99, acl_tags=[TENANT_A]),           # ok
        _hit(score=0.99, acl_tags=[TENANT_B]),           # restricted
        _hit(score=settings.retrieval_floor - 0.01, acl_tags=[TENANT_A]),  # dropped
    ]
    result = trust_filter(hits, acl_tags=[TENANT_A])

    assert len(result) == 2
    assert len(written) == 1, "one audit row per call, not per chunk"
    outputs = written[0]["outputs"]
    assert outputs == {"input_count": 3, "output_count": 2, "restricted_count": 1}
