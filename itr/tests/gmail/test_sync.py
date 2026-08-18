"""
Tests for Gmail -> MinIO raw sync.

The headline guarantee is "never write the same mail twice", and per handover
doc section 8 the bucket is the authority: a HEAD on the derived key before the
PUT. Most of these attack that — repeat runs, re-discovery, a wiped ledger,
concurrent writers, and malformed input.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from scout.gmail.raw_ledger import RawSyncState
from scout.gmail.sync import GmailRawSync, RawSyncResult
from scout.raw.minio_client import PutResult

# ── fakes ─────────────────────────────────────────────────────────────────────


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _raw_message(
    mid: str, *, ms: int, attachment: bool = False, sender: str | None = None
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [
        {
            "partId": "0",
            "mimeType": "text/plain",
            "filename": "",
            "headers": [],
            "body": {"size": 10, "data": _b64(f"Body of {mid}")},
        }
    ]
    if attachment:
        parts.append(
            {
                "partId": "1",
                "mimeType": "application/pdf",
                "filename": f"{mid}.pdf",
                "headers": [],
                "body": {"size": 9, "attachmentId": f"att-{mid}"},
            }
        )
    return {
        "id": mid,
        "threadId": f"t-{mid}",
        "historyId": 100,
        "internalDate": str(ms),
        "labelIds": ["INBOX"],
        "snippet": mid,
        "payload": {
            "partId": "",
            "mimeType": "multipart/mixed",
            "filename": "",
            "headers": [
                {"name": "From", "value": sender or f"{mid}@example.com"},
                {"name": "To", "value": "support@motiveminds.com"},
                {"name": "Subject", "value": f"Subject {mid}"},
            ],
            "body": {"size": 0},
            "parts": parts,
        },
    }


class FakeGmail:
    def __init__(self, messages: dict[str, dict[str, Any]], history_id: str = "500") -> None:
        self.messages = messages
        self.history_id = history_id
        self.get_calls: list[str] = []
        self.history_ids_to_return: list[str] = []
        self.history_error: Exception | None = None
        # Gmail really does re-surface known messages (label changes,
        # un-trashing) — the harshest realistic input for the dedup guarantee.
        self.history_returns_all = False

    def get_profile(self) -> dict[str, Any]:
        return {"emailAddress": "support@motiveminds.com", "historyId": self.history_id}

    def get_message(self, message_id: str, *, format: str = "full") -> dict[str, Any]:
        self.get_calls.append(message_id)
        return self.messages[message_id]

    def get_attachment_bytes(self, *, message_id: str, attachment_id: str) -> bytes:
        return b"%PDF-1.4\n"

    def iter_all_message_ids(self, **kwargs: Any):
        limit = kwargs.get("limit")
        for i, mid in enumerate(self.messages):
            if limit is not None and i >= limit:
                return
            yield mid, None

    def list_history_message_ids(self, *, start_history_id: str, **kwargs: Any):
        if self.history_error:
            raise self.history_error
        if self.history_returns_all:
            return list(self.messages), self.history_id
        return list(self.history_ids_to_return), self.history_id

    def close(self) -> None:
        return


@dataclass
class FakeLake:
    bucket: str = "raw"
    endpoint: str = "http://fake:9000"
    objects: dict[str, bytes] = field(default_factory=dict)
    put_calls: list[str] = field(default_factory=list)
    head_calls: list[str] = field(default_factory=list)
    fail_on: set[str] = field(default_factory=set)
    meta: dict[str, dict[str, str]] = field(default_factory=dict)

    def ensure_bucket(self) -> None:
        return

    def stat_object(self, key: str):
        self.head_calls.append(key)
        if key not in self.objects:
            return None
        return {
            "key": key,
            "size_bytes": len(self.objects[key]),
            "etag": "e",
            "metadata": self.meta.get(key, {}),
        }

    def object_exists(self, key: str) -> bool:
        return self.stat_object(key) is not None

    def put_bytes(self, *, key: str, body: bytes, content_type: str = "", metadata=None):
        if key in self.fail_on:
            raise RuntimeError(f"simulated MinIO failure for {key}")
        self.put_calls.append(key)
        self.objects[key] = body
        self.meta[key] = dict(metadata or {})
        return PutResult(bucket=self.bucket, key=key, size_bytes=len(body), etag="e", sha256="s")

    def put_raw(self, data: bytes, key: str, *, content_type: str = "") -> str:
        self.put_bytes(key=key, body=data, content_type=content_type)
        return key

    def get_raw(self, object_path: str) -> bytes:
        return self.objects[object_path]


class FakeLedger:
    """Audit + cursor only. Never consulted for correctness."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.skips: list[dict[str, Any]] = []
        self.state: RawSyncState | None = None

    def ensure_schema(self) -> None:
        return

    def already_written(self, account_id: str, message_ids: list[str]) -> set[str]:
        return {m for m in message_ids if (account_id, m) in self.rows}

    def get(self, account_id: str, gmail_message_id: str):
        return self.rows.get((account_id, gmail_message_id))

    def record_written(self, *, account_id, gmail_message_id, object_key, **kw) -> None:
        self.rows[(account_id, gmail_message_id)] = {"object_key": object_key, **kw}

    def record_skipped(self, *, account_id, gmail_message_id, reason, detail="") -> None:
        self.skips.append({"id": gmail_message_id, "reason": reason, "detail": detail})

    def get_state(self, account_id: str) -> RawSyncState | None:
        return self.state

    def save_state(self, state: RawSyncState) -> None:
        self.state = state

    def counts(self, account_id: str) -> dict[str, int]:
        return {"written": len(self.rows), "skipped": len(self.skips)}


class FakeRunStore:
    """In-memory raw_ingest.runs, so the real connector_run flow is exercised."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.stage_events: list[dict[str, Any]] = []

    def start(self, *, tenant_id, source_system, mode, cursor_before, started_at):
        run_id = uuid.uuid4()
        self.runs[str(run_id)] = {
            "status": "running",
            "mode": mode,
            "cursor_before": cursor_before,
            "source_system": source_system,
        }
        return run_id

    def finish(self, run_id, **kw: Any) -> None:
        self.runs[str(run_id)].update(kw)

    def add_stage_event(self, run_id, **kw: Any) -> None:
        self.stage_events.append({"run_id": str(run_id), **kw})

    # convenience for assertions
    @property
    def last_run(self) -> dict[str, Any]:
        return list(self.runs.values())[-1]

    @property
    def stages(self) -> list[str]:
        return [e["stage"] for e in self.stage_events]


def _sync(gmail, ledger, lake, **kw: Any) -> GmailRawSync:
    return GmailRawSync(
        client=gmail,
        ledger=ledger,
        lake=lake,
        run_store=kw.get("run_store") or FakeRunStore(),
        account_id="support@motiveminds.com",
        prefix="gmail",
        layout="flat",
        partition_by="received",
        object_pattern="email_{message_id}.json",
        max_attachment_bytes=1_000_000,
        max_per_run=kw.get("max_per_run", 100),
        include_spam_trash=True,
        query="",
        page_size=100,
        use_ledger_prefilter=kw.get("use_ledger_prefilter", True),
    )


AUG14 = int(datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)
AUG15 = int(datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)


# ── the duplicate guarantee ───────────────────────────────────────────────────


def test_first_run_writes_message_id_named_objects():
    gmail = FakeGmail({
        "18abc123": _raw_message("18abc123", ms=AUG14),
        "18abc456": _raw_message("18abc456", ms=AUG14),
    })
    ledger, lake = FakeLedger(), FakeLake()
    result = _sync(gmail, ledger, lake).run()

    assert result.written == 2
    assert sorted(lake.objects) == [
        "gmail/2026/08/14/email_18abc123.json",
        "gmail/2026/08/14/email_18abc456.json",
    ]


def test_head_is_called_before_every_put():
    """Section 8: stat_object on the exact path precedes the write."""
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    ledger, lake = FakeLedger(), FakeLake()
    _sync(gmail, ledger, lake).run()

    assert lake.head_calls == ["gmail/2026/08/14/email_m1.json"]
    assert lake.put_calls == ["gmail/2026/08/14/email_m1.json"]


def test_rediscovered_message_is_neither_refetched_nor_rewritten():
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    ledger, lake = FakeLedger(), FakeLake()

    _sync(gmail, ledger, lake).run()
    calls_after_first = len(gmail.get_calls)

    gmail.history_returns_all = True
    second = _sync(gmail, ledger, lake).run()

    assert second.written == 0
    assert second.skipped_known == 1
    assert len(lake.put_calls) == 1
    assert len(gmail.get_calls) == calls_after_first


def test_bucket_blocks_duplicate_even_with_no_ledger_at_all():
    """
    The doc's core claim: dedup needs no tracking table. With the ledger
    removed entirely, a second run must still write nothing.
    """
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    lake = FakeLake()

    first = _sync(gmail, None, lake).run()
    assert first.written == 1

    gmail.history_returns_all = True
    second = _sync(gmail, None, lake).run()

    assert second.written == 0
    assert second.skipped_duplicates == 1
    assert len(lake.objects) == 1
    assert len(lake.put_calls) == 1


def test_wiped_ledger_does_not_cause_a_rewrite():
    """Losing the ledger costs quota (a re-fetch), never a duplicate object."""
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    ledger, lake = FakeLedger(), FakeLake()
    _sync(gmail, ledger, lake).run()

    ledger.rows.clear()  # simulate a dropped table / fresh database
    ledger.state = None
    second = _sync(gmail, ledger, lake).run()

    assert second.written == 0
    assert second.skipped_duplicates == 1
    assert len(lake.put_calls) == 1


def test_wiped_ledger_heals_itself_from_object_metadata():
    """
    After a wipe the audit row is rebuilt from what HEAD returns, so the
    pre-filter warms back up instead of re-fetching from Gmail forever.
    """
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14, attachment=True)})
    ledger, lake = FakeLedger(), FakeLake()
    _sync(gmail, ledger, lake).run()
    original = dict(ledger.rows[("support@motiveminds.com", "m1")])

    ledger.rows.clear()
    ledger.state = None
    _sync(gmail, ledger, lake).run()

    healed = ledger.rows.get(("support@motiveminds.com", "m1"))
    assert healed is not None, "ledger row should be rebuilt from object metadata"
    assert healed["object_key"] == original["object_key"]
    assert healed["content_sha256"] == original["content_sha256"]
    assert healed["attachment_count"] == 1

    # Third run now hits the warm pre-filter: no Gmail fetch, no HEAD.
    calls_before = len(gmail.get_calls)
    gmail.history_returns_all = True
    third = _sync(gmail, ledger, lake).run()
    assert third.skipped_known == 1
    assert len(gmail.get_calls) == calls_before


def test_ten_consecutive_runs_produce_exactly_one_object():
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    gmail.history_returns_all = True
    ledger, lake = FakeLedger(), FakeLake()
    for _ in range(10):
        _sync(gmail, ledger, lake).run()
    assert len(lake.objects) == 1
    assert lake.put_calls.count("gmail/2026/08/14/email_m1.json") == 1


def test_failed_put_is_retried_and_lands_on_the_same_key():
    """Section 16: a partial/failed write must not count as stored."""
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    ledger = FakeLedger()
    lake = FakeLake(fail_on={"gmail/2026/08/14/email_m1.json"})

    first = _sync(gmail, ledger, lake).run()
    assert first.failed == 1
    assert lake.objects == {}
    assert ledger.rows == {}, "must not be recorded as stored"

    lake.fail_on.clear()
    gmail.history_returns_all = True
    second = _sync(gmail, ledger, lake).run()
    assert second.written == 1
    assert list(lake.objects) == ["gmail/2026/08/14/email_m1.json"]


def test_concurrent_writers_converge_on_one_key():
    """
    Two syncers racing the same message. Deterministic keys mean the worst case
    is writing identical bytes twice to one key — never two objects.
    """
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    lake = FakeLake()
    a, b = _sync(gmail, None, lake), _sync(gmail, None, lake)

    ra, rb = RawSyncResult(account_id="x"), RawSyncResult(account_id="x")
    a.ingest_message("m1", ra)
    b.ingest_message("m1", rb)

    assert len(lake.objects) == 1
    assert ra.written == 1
    assert rb.skipped_duplicates == 1


def test_partition_uses_received_date_so_backfill_is_stable():
    gmail = FakeGmail({
        "m1": _raw_message("m1", ms=AUG14),
        "m2": _raw_message("m2", ms=AUG15),
    })
    ledger, lake = FakeLedger(), FakeLake()
    _sync(gmail, ledger, lake).run()
    assert "gmail/2026/08/14/email_m1.json" in lake.objects
    assert "gmail/2026/08/15/email_m2.json" in lake.objects


# ── malformed input (section 16) ──────────────────────────────────────────────


def test_message_with_no_id_is_skipped_and_logged():
    bad = _raw_message("m1", ms=AUG14)
    bad["id"] = ""
    gmail = FakeGmail({"m1": bad})
    ledger, lake = FakeLedger(), FakeLake()

    result = _sync(gmail, ledger, lake).run()

    assert result.skipped_malformed == 1
    assert result.written == 0
    assert lake.objects == {}
    assert ledger.skips[0]["reason"] == "malformed"


def test_message_with_unsafe_id_is_skipped_not_written_elsewhere():
    bad = _raw_message("m1", ms=AUG14)
    bad["id"] = "../../escape"
    gmail = FakeGmail({"m1": bad})
    ledger, lake = FakeLedger(), FakeLake()

    result = _sync(gmail, ledger, lake).run()

    assert result.skipped_malformed == 1
    assert lake.objects == {}
    assert ledger.skips[0]["reason"] == "invalid_message_id"


# ── content ───────────────────────────────────────────────────────────────────


def test_written_object_matches_handover_section_6_shape():
    gmail = FakeGmail({"18abc123": _raw_message("18abc123", ms=AUG14, attachment=True)})
    ledger, lake = FakeLedger(), FakeLake()
    _sync(gmail, ledger, lake).run()

    doc = json.loads(lake.objects["gmail/2026/08/14/email_18abc123.json"].decode("utf-8"))
    # Exactly the keys the handover doc's example specifies.
    for key in ("source", "message_id", "thread_id", "from", "to", "subject",
                "body", "received_at"):
        assert key in doc, f"handover section 6 requires top-level {key!r}"
    assert doc["source"] == "gmail"
    assert doc["message_id"] == "18abc123"
    assert doc["thread_id"] == "t-18abc123"
    assert doc["from"] == "18abc123@example.com"
    assert doc["to"] == "support@motiveminds.com"
    assert doc["subject"] == "Subject 18abc123"
    assert doc["body"] == "Body of 18abc123"
    assert doc["received_at"].startswith("2026-08-14T")


def test_written_object_keeps_full_fidelity_extras():
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14, attachment=True)})
    ledger, lake = FakeLedger(), FakeLake()
    result = _sync(gmail, ledger, lake).run()

    assert result.attachments_written == 1
    doc = json.loads(lake.objects["gmail/2026/08/14/email_m1.json"].decode("utf-8"))
    assert doc["attachment_count"] == 1
    att = doc["attachments"][0]
    # Task 6: attachment bytes live in their own object beside the message.
    assert att["object_path"] == "gmail/2026/08/14/m1/attachments/att-m1_m1.pdf"
    assert lake.objects[att["object_path"]] == b"%PDF-1.4\n"
    assert att["sha256"]
    assert doc["mime_tree"]["mimeType"] == "multipart/mixed"
    assert doc["headers_raw"]
    assert doc["label_ids"] == ["INBOX"]


def test_every_message_is_ingested():
    gmail = FakeGmail({f"m{i}": _raw_message(f"m{i}", ms=AUG14) for i in range(3)})
    ledger, lake = FakeLedger(), FakeLake()
    assert _sync(gmail, ledger, lake).run().written == 3


# ── Task 8 drops (system / bulk) — still applied; no sender allowlist ─────────

VIHAAN = "Vihaan Banerjee <motiveminds.vihaan@gmail.com>"
JENNIFER = "Jennifer Carter <motiveminds.jennifer@gmail.com>"
OJASVI = "Ojasvi Goda <motiveminds.ojasvi@gmail.com>"


def _mixed_mailbox() -> FakeGmail:
    return FakeGmail({
        "c1": _raw_message("c1", ms=AUG14, sender=VIHAAN),
        "c2": _raw_message("c2", ms=AUG14, sender=JENNIFER),
        "c3": _raw_message("c3", ms=AUG14, sender=OJASVI),
        "n1": _raw_message("n1", ms=AUG14, sender="Rohan <rohancherian289@gmail.com>"),
        "n2": _raw_message("n2", ms=AUG14, sender="Google <no-reply@google.com>"),
        "n3": _raw_message("n3", ms=AUG14, sender="Me <motiveminds.itsupport@gmail.com>"),
    })


def test_all_non_system_mail_is_stored():
    """Whole mailbox is ingested; only Task 8 system/bulk senders are dropped."""
    gmail, ledger, lake = _mixed_mailbox(), FakeLedger(), FakeLake()
    result = _sync(gmail, ledger, lake).run()

    assert result.written == 5
    assert result.skipped_dropped == 1
    assert sorted(lake.objects) == [
        "gmail/2026/08/14/email_c1.json",
        "gmail/2026/08/14/email_c2.json",
        "gmail/2026/08/14/email_c3.json",
        "gmail/2026/08/14/email_n1.json",
        "gmail/2026/08/14/email_n3.json",
    ]


def test_system_mail_is_logged_not_silently_dropped():
    gmail, ledger, lake = _mixed_mailbox(), FakeLedger(), FakeLake()
    _sync(gmail, ledger, lake).run()

    reasons = {s["reason"] for s in ledger.skips}
    assert reasons == {"system_sender"}
    assert len(ledger.skips) == 1
    assert any("no-reply@google.com" in s["detail"] for s in ledger.skips)


def test_system_mail_is_dropped_with_its_own_reason_code():
    """Task 8: a Google alert must not reach the corpus."""
    store = FakeRunStore()
    gmail, ledger, lake = _mixed_mailbox(), FakeLedger(), FakeLake()
    _sync(gmail, ledger, lake, run_store=store).run()

    assert any(e.get("reason") == "system_sender" for e in store.last_run["errors"])
    assert "gmail/2026/08/14/email_n2.json" not in lake.objects


def test_google_security_alert_is_rejected():
    """Slice-1 Task 8: these must never reach the corpus."""
    gmail = FakeGmail({
        "g1": _raw_message("g1", ms=AUG14, sender="Google <no-reply@google.com>")
    })
    ledger, lake = FakeLedger(), FakeLake()
    assert _sync(gmail, ledger, lake).run().written == 0


def test_optional_listing_query_is_passed_through():
    gmail, ledger, lake = _mixed_mailbox(), FakeLedger(), FakeLake()
    sync = GmailRawSync(
        client=gmail, ledger=ledger, lake=lake,
        account_id="support@motiveminds.com",
        query="in:inbox",
    )
    assert sync._listing_query() == "in:inbox"
    assert _sync(gmail, ledger, lake)._listing_query() is None


def test_history_path_ingests_all_non_system_mail():
    """history.list takes no query; Task 8 still drops after fetch."""
    gmail, ledger, lake = _mixed_mailbox(), FakeLedger(), FakeLake()
    gmail.history_returns_all = True
    ledger.state = RawSyncState(
        account_id="support@motiveminds.com", history_id="1", backfill_done=True
    )
    result = _sync(gmail, ledger, lake).run()

    assert result.mode == "history"
    assert result.written == 5
    assert result.skipped_dropped == 1


def test_attachment_failure_does_not_lose_the_message():
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14, attachment=True)})

    def boom(**kwargs: Any) -> bytes:
        raise RuntimeError("attachment gone")

    gmail.get_attachment_bytes = boom  # type: ignore[assignment]
    ledger, lake = FakeLedger(), FakeLake()
    result = _sync(gmail, ledger, lake).run()

    assert result.written == 1
    doc = json.loads(lake.objects["gmail/2026/08/14/email_m1.json"].decode("utf-8"))
    assert doc["attachments"][0]["object_path"] is None
    assert "attachment gone" in doc["attachments"][0]["error"]


# ── cursor behaviour ──────────────────────────────────────────────────────────


def test_history_cursor_advances_after_backfill_completes():
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)}, history_id="900")
    ledger, lake = FakeLedger(), FakeLake()
    result = _sync(gmail, ledger, lake).run()
    assert result.backfill_done is True
    assert ledger.state is not None and ledger.state.history_id == "900"


def test_expired_history_falls_back_to_full_list():
    import httpx

    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)})
    gmail.history_error = httpx.HTTPStatusError(
        "gone",
        request=httpx.Request("GET", "https://gmail.googleapis.com"),
        response=httpx.Response(404),
    )
    ledger, lake = FakeLedger(), FakeLake()
    ledger.state = RawSyncState(
        account_id="support@motiveminds.com", history_id="1", backfill_done=True
    )

    result = _sync(gmail, ledger, lake).run()
    assert result.mode == "backfill"
    assert result.written == 1


def test_history_mode_used_once_backfill_is_done():
    gmail = FakeGmail({"m1": _raw_message("m1", ms=AUG14)}, history_id="950")
    gmail.history_ids_to_return = ["m1"]
    ledger, lake = FakeLedger(), FakeLake()
    ledger.state = RawSyncState(
        account_id="support@motiveminds.com", history_id="900", backfill_done=True
    )

    result = _sync(gmail, ledger, lake).run()
    assert result.mode == "history"
    assert result.written == 1


def test_max_per_run_bounds_a_single_invocation():
    gmail = FakeGmail({f"m{i}": _raw_message(f"m{i}", ms=AUG14) for i in range(10)})
    ledger, lake = FakeLedger(), FakeLake()
    result = _sync(gmail, ledger, lake, max_per_run=3).run()
    assert result.written == 3


@pytest.mark.parametrize("runs", [2, 3, 5])
def test_repeated_runs_over_growing_mailbox_never_duplicate(runs: int):
    messages = {"m1": _raw_message("m1", ms=AUG14)}
    gmail = FakeGmail(messages)
    gmail.history_returns_all = True
    ledger, lake = FakeLedger(), FakeLake()

    for i in range(runs):
        messages[f"new{i}"] = _raw_message(f"new{i}", ms=AUG14)
        _sync(gmail, ledger, lake).run()

    assert len(lake.objects) == len(messages)
    assert len(lake.put_calls) == len(set(lake.put_calls))
    assert sorted(gmail.get_calls) == sorted(messages)


# ── Task 6: run tracking, stages, resilience ─────────────────────────────────


def test_run_emits_all_seven_stages_in_order():
    """The console renders all seven; a missing one reads as a broken pipeline."""
    store = FakeRunStore()
    gmail = FakeGmail({"m1": _raw_message("m1", ms=1755158400000)})
    _sync(gmail, FakeLedger(), FakeLake(), run_store=store).run()

    assert store.stages[:2] == ["connect", "discover"]
    assert set(store.stages) == {
        "connect", "discover", "extract", "redact", "normalise", "resolve", "index",
    }
    assert store.stages[-1] == "index"
    assert all(0 <= e["progress_pct"] <= 100 for e in store.stage_events)
    # Log lines are rendered directly in the console, so they must read as
    # sentences with counts, not debug output.
    assert all(e["log_line"] and e["log_line"][0].isupper() for e in store.stage_events)


def test_run_records_counters_and_cursors():
    store = FakeRunStore()
    gmail = FakeGmail({f"m{i}": _raw_message(f"m{i}", ms=1755158400000) for i in range(3)})
    _sync(gmail, FakeLedger(), FakeLake(), run_store=store).run()

    run = store.last_run
    assert run["status"] == "success"
    assert run["mode"] == "backfill"
    assert run["messages_seen"] == 3
    assert run["messages_written"] == 3
    assert run["cursor_after"] == "500"


def test_failed_run_is_marked_failed_with_traceback():
    store = FakeRunStore()
    gmail = FakeGmail({"m1": _raw_message("m1", ms=1755158400000)})

    def boom() -> dict[str, Any]:
        raise RuntimeError("gmail unreachable")

    gmail.get_profile = boom  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        _sync(gmail, FakeLedger(), FakeLake(), run_store=store).run()

    run = store.last_run
    assert run["status"] == "failed"
    assert any("gmail unreachable" in str(e.get("error", "")) for e in run["errors"])
    assert any("traceback" in e for e in run["errors"])


def test_expired_history_is_recorded_as_history_id_expired():
    """Doc: record history_id_expired and fall back rather than crashing."""
    store = FakeRunStore()
    gmail = FakeGmail({"m1": _raw_message("m1", ms=1755158400000)})
    gmail.history_error = httpx.HTTPStatusError(
        "expired", request=httpx.Request("GET", "http://x"),
        response=httpx.Response(404, request=httpx.Request("GET", "http://x")),
    )
    ledger = FakeLedger()
    ledger.state = RawSyncState(account_id="support@motiveminds.com",
                                history_id="1985", backfill_done=True)

    result = _sync(gmail, ledger, FakeLake(), run_store=store).run()

    assert result.mode == "backfill", "must fall back to a full backfill"
    assert any(e.get("reason") == "history_id_expired" for e in store.last_run["errors"])


def test_rate_limited_gmail_call_retries_with_jitter(monkeypatch):
    """429 must back off and retry, not fail the message."""
    from scout.gmail import sync as sync_mod

    slept: list[float] = []
    monkeypatch.setattr(sync_mod.time, "sleep", slept.append)

    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError(
                "rate", request=req, response=httpx.Response(429, request=req)
            )
        return "ok"

    assert sync_mod.gmail_retry("probe", flaky) == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2
    assert slept[1] > slept[0], "delay must grow"
    # Jitter means the delay is never exactly the base value.
    assert slept[0] != sync_mod._GMAIL_BASE_DELAY


def test_non_rate_limit_error_is_not_retried():
    from scout.gmail import sync as sync_mod

    req = httpx.Request("GET", "http://x")

    def forbidden() -> str:
        raise httpx.HTTPStatusError(
            "bad", request=req, response=httpx.Response(400, request=req)
        )

    with pytest.raises(httpx.HTTPStatusError):
        sync_mod.gmail_retry("probe", forbidden)
