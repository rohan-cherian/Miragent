"""
Tests for pii.redact_and_audit() — the additive audit wrapper.

Skips cleanly without a live database (the audit rows land in
itr360.decision_audit). redact() itself is deliberately NOT re-tested
here — tests/test_pii.py owns that, and this task's contract is that
redact() is provably unchanged (its file-level source guard still holds).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from scout.config import settings
from scout.governance import audit
from scout.governance.pii import RedactionError, redact_and_audit


def _skip_without_db():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping redaction-audit tests")


def _rows_since(cutoff, action: str, marker: str):
    return [
        row
        for row in audit.list(category="redaction", from_ts=cutoff)
        if row.action == action and (row.outputs or {}).get("source") == marker
    ]


def test_clean_redaction_writes_one_redact_row():
    _skip_without_db()
    marker = f"test-src-{uuid.uuid4().hex[:8]}"
    cutoff = datetime.now(UTC) - timedelta(seconds=5)

    result = redact_and_audit("No personal data in this sentence.", source=marker)

    assert result.status in ("clean", "redacted")
    rows = _rows_since(cutoff, "redact", marker)
    assert len(rows) == 1, "exactly one audit row per call"
    row = rows[0]
    assert row.category == "redaction"
    assert row.actor == "system"
    assert row.outputs["status"] == result.status
    assert row.outputs["pii_count"] == len(result.pii_map)
    assert row.case_id is None, "documented: redaction precedes case correlation"


def test_forced_failure_writes_redact_failed_row_and_reraises(monkeypatch):
    _skip_without_db()
    marker = f"test-src-{uuid.uuid4().hex[:8]}"
    cutoff = datetime.now(UTC) - timedelta(seconds=5)
    monkeypatch.setenv("PRESIDIO_FORCE_FAIL", "true")

    with pytest.raises(RedactionError) as excinfo:
        redact_and_audit("anything", source=marker)

    # the ORIGINAL exception propagated (fail-closed untouched)...
    assert "PRESIDIO_FORCE_FAIL" in str(excinfo.value)
    # ...AND the failure left an audit row
    rows = _rows_since(cutoff, "redact_failed", marker)
    assert len(rows) == 1
    assert "PRESIDIO_FORCE_FAIL" in rows[0].outputs["error"]


def test_audit_backend_failure_never_swallows_the_redaction_error(monkeypatch):
    """The guard: an audit hiccup warns; it must not replace or suppress the
    RedactionError, and on the happy path must not fail the redaction."""
    from scout.governance import pii as pii_module

    def _boom(**kwargs):
        raise RuntimeError("audit backend unreachable")

    monkeypatch.setattr(audit, "write", _boom)

    # happy path: result still returned despite the audit failure
    result = redact_and_audit("No personal data here either.", source="guard-test")
    assert result.status in ("clean", "redacted")

    # failure path: still the ORIGINAL RedactionError, not the RuntimeError
    monkeypatch.setenv("PRESIDIO_FORCE_FAIL", "true")
    with pytest.raises(RedactionError):
        pii_module.redact_and_audit("anything", source="guard-test")
