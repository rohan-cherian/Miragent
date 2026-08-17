"""
Integration tests for the re-grained src_gmail store (Task 5).

The point of the re-grain is that a Gmail thread with three messages is ONE
thread row with message_count 3 — not three tickets. That is the doc's
acceptance check and it is the first test below.

Every test uses a unique tenant_id, so runs never collide with each other or
with real data, and rolls back rather than committing.

Skipped automatically when Postgres is not reachable.

    docker compose -f docker-compose.zendesk-emulator.yml up -d
    poetry run python scripts/load_gmail_schema.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from scout.config import settings
from scout.gmail.raw_ledger import GmailRawLedger
from scout.gmail.store import (
    MessageRow,
    recompute_thread_rollup,
    upsert_attachment,
    upsert_mailbox,
    upsert_message,
    upsert_thread,
)


@pytest.fixture(scope="module")
def _schema_ready() -> None:
    ledger = GmailRawLedger(settings.gmail_database_url)
    try:
        ledger.connect().close()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres unavailable: {type(exc).__name__}")
    ledger.ensure_schema()


@pytest.fixture
def conn(_schema_ready) -> psycopg.Connection:
    """Caller-supplied connection, rolled back so nothing persists."""
    with psycopg.connect(settings.gmail_database_url) as c:
        yield c
        c.rollback()


@pytest.fixture
def tenant() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def run_id() -> str:
    return str(uuid.uuid4())


def _msg(external_id: str, internal_date_ms: int, **kw) -> MessageRow:
    kw.setdefault("object_path", f"gmail/2026/08/14/email_{external_id}.json")
    kw.setdefault("checksum_sha256", "0" * 64)
    return MessageRow(
        external_id=external_id,
        internal_date_ms=internal_date_ms,
        **kw,
    )


def _seed_thread(conn, tenant, run_id, *, thread_ext="t-1"):
    mailbox = upsert_mailbox(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        external_id="acct-1",
        address="support@example.com",
    )
    thread = upsert_thread(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        external_id=thread_ext,
        mailbox_id=mailbox.id,
    )
    return mailbox, thread


# ── the doc's acceptance check ───────────────────────────────────────────────


def test_three_message_conversation_is_one_thread(conn, tenant, run_id):
    """E1/E2/E3: ONE thread row, message_count 3, three message rows.

    Uses only the four upserts — no explicit rollup call — because the doc
    requires upsert_thread itself to recompute from its child rows.
    """
    mailbox, thread = _seed_thread(conn, tenant, run_id)

    for i, ts in enumerate([1_000, 2_000, 3_000], start=1):
        upsert_message(
            conn,
            tenant_id=tenant,
            connector_run_id=run_id,
            thread_id=thread.id,
            mailbox_id=mailbox.id,
            message=_msg(f"m-{i}", ts),
        )

    # Re-upserting the thread is what refreshes the rollup.
    upsert_thread(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        external_id="t-1",
        mailbox_id=mailbox.id,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.external_id, t.message_count, count(m.id)
              FROM src_gmail.thread t
              JOIN src_gmail.message m ON m.thread_id = t.id
             WHERE t.tenant_id = %s
             GROUP BY 1, 2
            """,
            (tenant,),
        )
        rows = cur.fetchall()

    assert rows == [("t-1", 3, 3)], "a 3-message conversation must be ONE thread"

    with conn.cursor() as cur:
        cur.execute(
            """SELECT first_internal_date_ms, last_internal_date_ms
                 FROM src_gmail.thread WHERE tenant_id = %s""",
            (tenant,),
        )
        assert cur.fetchone() == (1_000, 3_000)


def test_upsert_thread_recomputes_rollup_itself(conn, tenant, run_id):
    """The doc puts the recompute inside upsert_thread, not on the caller."""
    mailbox, thread = _seed_thread(conn, tenant, run_id)
    # A brand-new thread has no children yet, so the rollup starts empty.
    with conn.cursor() as cur:
        cur.execute(
            """SELECT message_count, first_internal_date_ms, last_internal_date_ms
                 FROM src_gmail.thread WHERE id = %s""",
            (thread.id,),
        )
        assert cur.fetchone() == (0, None, None)

    for i, ts in enumerate([7_000, 2_000], start=1):
        upsert_message(
            conn,
            tenant_id=tenant,
            connector_run_id=run_id,
            thread_id=thread.id,
            mailbox_id=mailbox.id,
            message=_msg(f"m-{i}", ts),
        )

    refreshed = upsert_thread(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        external_id="t-1",
        mailbox_id=mailbox.id,
    )
    assert refreshed.id == thread.id
    assert refreshed.was_new is False

    with conn.cursor() as cur:
        cur.execute(
            """SELECT message_count, first_internal_date_ms, last_internal_date_ms
                 FROM src_gmail.thread WHERE id = %s""",
            (thread.id,),
        )
        assert cur.fetchone() == (2, 2_000, 7_000)


# ── idempotency: zero duplicates, zero field drift ───────────────────────────


def test_rerun_creates_no_duplicates_and_reports_not_new(conn, tenant, run_id):
    mailbox, thread = _seed_thread(conn, tenant, run_id)
    msg = _msg("m-1", 1_000, subject="Original")

    first = upsert_message(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        message=msg,
    )
    assert first.was_new is True

    second = upsert_message(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        message=msg,
    )
    assert second.was_new is False
    assert second.id == first.id, "same external_id must resolve to the same row"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM src_gmail.message WHERE tenant_id = %s",
            (tenant,),
        )
        assert cur.fetchone()[0] == 1


def test_upsert_updates_fields_in_place(conn, tenant, run_id):
    """Re-running with changed content updates rather than inserting."""
    mailbox, thread = _seed_thread(conn, tenant, run_id)
    upsert_message(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        message=_msg("m-1", 1_000, subject="Before", quoted_stripped=False),
    )

    later_run = str(uuid.uuid4())
    result = upsert_message(
        conn,
        tenant_id=tenant,
        connector_run_id=later_run,
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        message=_msg("m-1", 1_000, subject="After", quoted_stripped=True),
    )
    assert result.was_new is False

    with conn.cursor() as cur:
        cur.execute(
            """SELECT subject, quoted_stripped, connector_run_id
                 FROM src_gmail.message WHERE tenant_id = %s""",
            (tenant,),
        )
        subject, stripped, stamped_run = cur.fetchone()

    assert subject == "After"
    assert stripped is True
    assert str(stamped_run) == later_run, "latest run must be stamped on the row"


def test_mailbox_and_thread_are_idempotent(conn, tenant, run_id):
    first_mailbox, first_thread = _seed_thread(conn, tenant, run_id)
    second_mailbox, second_thread = _seed_thread(conn, tenant, run_id)

    assert first_mailbox.was_new is True and second_mailbox.was_new is False
    assert first_mailbox.id == second_mailbox.id
    assert first_thread.was_new is True and second_thread.was_new is False
    assert first_thread.id == second_thread.id


# ── rollup is derived, not incremented ───────────────────────────────────────


def test_rollup_is_recomputed_not_incremented(conn, tenant, run_id):
    """Re-upserting the same messages must not inflate message_count."""
    mailbox, thread = _seed_thread(conn, tenant, run_id)

    for _pass in range(2):
        for i, ts in enumerate([5_000, 1_000], start=1):
            upsert_message(
                conn,
                tenant_id=tenant,
                connector_run_id=run_id,
                thread_id=thread.id,
                mailbox_id=mailbox.id,
                message=_msg(f"m-{i}", ts),
            )
        count, first_ms, last_ms = recompute_thread_rollup(conn, thread.id)
        assert (count, first_ms, last_ms) == (2, 1_000, 5_000)


def test_rollup_on_empty_thread_is_zero(conn, tenant, run_id):
    _mailbox, thread = _seed_thread(conn, tenant, run_id)
    assert recompute_thread_rollup(conn, thread.id) == (0, None, None)


def test_rollup_rejects_unknown_thread(conn):
    with pytest.raises(ValueError):
        recompute_thread_rollup(conn, uuid.uuid4())


# ── tenant isolation ─────────────────────────────────────────────────────────


def test_same_external_id_across_tenants_are_separate_rows(conn, run_id):
    """The unique key is (tenant_id, source_system, external_id)."""
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    ids = set()
    for tenant in (tenant_a, tenant_b):
        mailbox, thread = _seed_thread(conn, tenant, run_id)
        result = upsert_message(
            conn,
            tenant_id=tenant,
            connector_run_id=run_id,
            thread_id=thread.id,
            mailbox_id=mailbox.id,
            message=_msg("shared-id", 1_000),
        )
        assert result.was_new is True
        ids.add(result.id)
    assert len(ids) == 2, "same message id under two tenants must not collide"


# ── attachments ──────────────────────────────────────────────────────────────


def test_attachment_upsert_and_idempotency(conn, tenant, run_id):
    mailbox, thread = _seed_thread(conn, tenant, run_id)
    message = upsert_message(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        message=_msg("m-1", 1_000),
    )

    kwargs = dict(
        tenant_id=tenant,
        connector_run_id=run_id,
        message_id=message.id,
        external_id="att-1",
        object_path="gmail/2026/08/14/m-1/attachments/att-1_report.pdf",
        checksum_sha256="a" * 64,
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
    )
    first = upsert_attachment(conn, **kwargs)
    second = upsert_attachment(conn, **kwargs)

    assert first.was_new is True
    assert second.was_new is False
    assert first.id == second.id


# ── provenance ───────────────────────────────────────────────────────────────


def test_provenance_stamped_on_every_row(conn, tenant, run_id):
    mailbox, thread = _seed_thread(conn, tenant, run_id)
    upsert_message(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        message=_msg("m-1", 1_000),
    )

    for table in ("mailbox", "thread", "message"):
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT source_system, is_synthetic, connector_run_id,
                           observed_at, valid_from
                      FROM src_gmail.{table} WHERE tenant_id = %s""",
                (tenant,),
            )
            source, synthetic, stamped_run, observed, valid = cur.fetchone()
        assert source == "gmail", table
        assert synthetic is False, table
        assert str(stamped_run) == run_id, table
        assert observed is not None and valid is not None, table


def test_explicit_observed_at_is_honoured(conn, tenant, run_id):
    stamp = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    upsert_mailbox(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        external_id="acct-1",
        address="support@example.com",
        observed_at=stamp,
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT observed_at, valid_from FROM src_gmail.mailbox WHERE tenant_id = %s",
            (tenant,),
        )
        observed, valid = cur.fetchone()
    assert observed == stamp
    assert valid == stamp, "valid_from defaults to observed_at"


# ── citext behaviour the DDL asks for ────────────────────────────────────────


def test_address_columns_are_case_insensitive(conn, tenant, run_id):
    mailbox, thread = _seed_thread(conn, tenant, run_id)
    upsert_message(
        conn,
        tenant_id=tenant,
        connector_run_id=run_id,
        thread_id=thread.id,
        mailbox_id=mailbox.id,
        message=_msg("m-1", 1_000, from_address="Alice@Example.COM"),
    )
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM src_gmail.message
                WHERE tenant_id = %s AND from_address = %s""",
            (tenant, "alice@example.com"),
        )
        assert cur.fetchone()[0] == 1, "from_address is citext, so case must not matter"
