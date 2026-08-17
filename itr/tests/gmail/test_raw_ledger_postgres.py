"""
Integration tests for the Postgres raw-lake bookkeeping.

This table is NOT the duplicate guard — the bucket HEAD is (handover doc
section 8). What is tested here is that the audit trail, the skip log and the
incremental cursor behave, and that re-recording is idempotent.

Skipped automatically when Postgres is not reachable.

    docker compose -f docker-compose.zendesk-emulator.yml up -d
    poetry run python scripts/load_gmail_schema.py
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from scout.config import settings
from scout.gmail.raw_ledger import GmailRawLedger, RawSyncState
from scout.raw.keys import build_object_key

PARTITION = date(2026, 8, 14)


def _ledger_or_skip() -> GmailRawLedger:
    ledger = GmailRawLedger(settings.gmail_database_url)
    try:
        ledger.connect().close()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres unavailable: {type(exc).__name__}")
    ledger.ensure_schema()
    return ledger


@pytest.fixture
def ledger() -> GmailRawLedger:
    return _ledger_or_skip()


@pytest.fixture
def account() -> str:
    """Unique per test so runs never collide with each other or real data."""
    return f"test-{uuid.uuid4().hex[:12]}@example.com"


def _record(ledger: GmailRawLedger, account: str, mid: str, **kw):
    ledger.record_written(
        account_id=account,
        gmail_message_id=mid,
        gmail_thread_id=kw.get("thread", f"t-{mid}"),
        object_key=build_object_key(partition=PARTITION, message_id=mid),
        partition=PARTITION,
        content_sha256=kw.get("sha", "abc123"),
        size_bytes=kw.get("size", 100),
        internal_date_ms=kw.get("ms", 1),
        attachment_count=kw.get("atts", 0),
    )


def test_record_written_stores_the_derived_key(ledger: GmailRawLedger, account: str):
    _record(ledger, account, "18abc123")
    row = ledger.get(account, "18abc123")
    assert row is not None
    assert row["object_key"] == "gmail/2026/08/14/email_18abc123.json"


def test_recording_twice_is_idempotent(ledger: GmailRawLedger, account: str):
    _record(ledger, account, "18abc123", size=100)
    _record(ledger, account, "18abc123", size=250)
    assert ledger.counts(account)["written"] == 1
    assert ledger.get(account, "18abc123")["size_bytes"] == 250


def test_already_written_prefilter(ledger: GmailRawLedger, account: str):
    _record(ledger, account, "m2")
    got = ledger.already_written(account, ["m1", "m2", "m3"])
    assert got == {"m2"}


def test_already_written_handles_empty_input(ledger: GmailRawLedger, account: str):
    assert ledger.already_written(account, []) == set()


def test_concurrent_records_for_one_message_yield_one_row(
    ledger: GmailRawLedger, account: str
):
    """Two syncers confirming the same write must not create two audit rows."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _record(ledger, account, "racy"), range(8)))
    assert ledger.counts(account)["written"] == 1


def test_distinct_messages_get_distinct_rows_and_keys(
    ledger: GmailRawLedger, account: str
):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: _record(ledger, account, f"m{i}"), range(16)))
    assert ledger.counts(account)["written"] == 16
    keys = {r["object_key"] for r in ledger.recent(account, limit=50)}
    assert len(keys) == 16


def test_skips_are_recorded_for_visibility(ledger: GmailRawLedger, account: str):
    ledger.record_skipped(
        account_id=account, gmail_message_id="", reason="malformed",
        detail="Gmail response has no message id",
    )
    assert ledger.counts(account)["skipped"] == 1
    skips = ledger.recent_skips(account, limit=5)
    assert skips[0]["reason"] == "malformed"
    assert "no message id" in skips[0]["detail"]


def test_state_round_trip(ledger: GmailRawLedger, account: str):
    ledger.save_state(
        RawSyncState(account_id=account, history_id="777", backfill_done=True)
    )
    state = ledger.get_state(account)
    assert state is not None
    assert state.history_id == "777"
    assert state.backfill_done is True

    ledger.save_state(RawSyncState(account_id=account, history_id="888", backfill_done=True))
    assert ledger.get_state(account).history_id == "888"


def test_unknown_account_has_no_state_or_rows(ledger: GmailRawLedger, account: str):
    assert ledger.get_state(account) is None
    assert ledger.counts(account) == {"written": 0, "skipped": 0}
    assert ledger.get(account, "nope") is None
