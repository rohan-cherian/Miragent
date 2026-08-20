"""
itr/scout/gmail/store.py — writes into the re-grained src_gmail (Task 5).

Four tables, one upsert each: mailbox -> thread -> message -> attachment.

Contract every function here honours:

* ``INSERT ... ON CONFLICT (tenant_id, source_system, external_id) DO UPDATE``,
  so re-running a sync causes zero duplicates and zero field drift. A second
  run over the same mailbox updates rows in place and reports was_new=False.
* Returns ``(id, was_new)``. was_new is derived from xmax, which Postgres
  leaves at 0 for a freshly inserted tuple and non-zero for one an UPDATE
  touched — RETURNING alone cannot tell the two apart.
* Takes an explicit ``connector_run_id`` and stamps it on every row alongside
  observed_at / valid_from, so any row can be traced to the run that wrote it.
* Takes a **caller-supplied** psycopg3 connection. This module never opens or
  closes one, and never commits — transaction boundaries belong to the caller,
  because Task 6 has to checkpoint the cursor only after the upserts commit.
* No Gmail API calls. Nothing here touches the network.

Only the object path and checksum are stored for message/attachment payloads;
the bytes themselves stay in MinIO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg

__all__ = [
    "UpsertResult",
    "upsert_mailbox",
    "upsert_thread",
    "upsert_message",
    "upsert_attachment",
    "recompute_thread_rollup",
]

SOURCE_SYSTEM = "gmail"


@dataclass(frozen=True)
class UpsertResult:
    """Row identity plus whether this call created it.

    Iterable, so ``row_id, was_new = upsert_message(...)`` reads naturally
    while callers that want the named fields still have them.
    """

    id: UUID
    was_new: bool

    def __iter__(self):
        yield self.id
        yield self.was_new


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _provenance(
    *,
    tenant_id: UUID | str,
    connector_run_id: UUID | str,
    is_synthetic: bool,
    observed_at: datetime | None,
    valid_from: datetime | None,
) -> dict[str, Any]:
    """The seven provenance values, resolved once per row."""
    stamp = observed_at or _now()
    return {
        "tenant_id": str(tenant_id),
        "source_system": SOURCE_SYSTEM,
        "is_synthetic": is_synthetic,
        "connector_run_id": str(connector_run_id),
        "observed_at": stamp,
        "valid_from": valid_from or stamp,
    }


def _columns(row: Any, *names: str) -> tuple[Any, ...]:
    """Read RETURNING columns whatever row factory the caller's connection uses.

    The connection is supplied by the caller, so the row may be a tuple (psycopg
    default) or a mapping (``dict_row``, which GmailRawLedger uses). Indexing
    positionally works for one and raises KeyError for the other, so resolve by
    name when we can and fall back to position.
    """
    if isinstance(row, dict):
        return tuple(row[n] for n in names)
    return tuple(row[i] for i in range(len(names)))


def _execute_upsert(
    conn: psycopg.Connection,
    sql: str,
    params: dict[str, Any],
) -> UpsertResult:
    """Run an upsert whose RETURNING clause is ``id, (xmax = 0) AS was_new``."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if row is None:  # pragma: no cover - DO UPDATE always returns a row
        raise RuntimeError("upsert returned no row; expected id and was_new")
    row_id, was_new = _columns(row, "id", "was_new")
    return UpsertResult(id=row_id, was_new=bool(was_new))


# ── mailbox ──────────────────────────────────────────────────────────────────

_MAILBOX_SQL = """
INSERT INTO src_gmail.mailbox (
    tenant_id, source_system, external_id, address,
    is_synthetic, connector_run_id, observed_at, valid_from
) VALUES (
    %(tenant_id)s, %(source_system)s, %(external_id)s, %(address)s,
    %(is_synthetic)s, %(connector_run_id)s, %(observed_at)s, %(valid_from)s
)
ON CONFLICT (tenant_id, source_system, external_id) DO UPDATE SET
    address          = EXCLUDED.address,
    is_synthetic     = EXCLUDED.is_synthetic,
    connector_run_id = EXCLUDED.connector_run_id,
    observed_at      = EXCLUDED.observed_at
RETURNING id, (xmax = 0) AS was_new
"""


def upsert_mailbox(
    conn: psycopg.Connection,
    *,
    tenant_id: UUID | str,
    connector_run_id: UUID | str,
    external_id: str,
    address: str,
    is_synthetic: bool = False,
    observed_at: datetime | None = None,
    valid_from: datetime | None = None,
) -> UpsertResult:
    """Upsert one mailbox. ``external_id`` is the Gmail account identifier."""
    params = _provenance(
        tenant_id=tenant_id,
        connector_run_id=connector_run_id,
        is_synthetic=is_synthetic,
        observed_at=observed_at,
        valid_from=valid_from,
    )
    params.update(external_id=external_id, address=address)
    return _execute_upsert(conn, _MAILBOX_SQL, params)


# ── thread ───────────────────────────────────────────────────────────────────

# message_count and the date bounds are deliberately NOT taken from the caller
# on conflict — recompute_thread_rollup derives them from the child rows, so a
# stale or partial caller-supplied count can never overwrite the truth.
_THREAD_SQL = """
INSERT INTO src_gmail.thread (
    tenant_id, source_system, external_id, mailbox_id,
    message_count, first_internal_date_ms, last_internal_date_ms,
    is_synthetic, connector_run_id, observed_at, valid_from
) VALUES (
    %(tenant_id)s, %(source_system)s, %(external_id)s, %(mailbox_id)s,
    0, NULL, NULL,
    %(is_synthetic)s, %(connector_run_id)s, %(observed_at)s, %(valid_from)s
)
ON CONFLICT (tenant_id, source_system, external_id) DO UPDATE SET
    mailbox_id       = EXCLUDED.mailbox_id,
    is_synthetic     = EXCLUDED.is_synthetic,
    connector_run_id = EXCLUDED.connector_run_id,
    observed_at      = EXCLUDED.observed_at
RETURNING id, (xmax = 0) AS was_new
"""

_THREAD_ROLLUP_SQL = """
UPDATE src_gmail.thread t
   SET message_count          = c.cnt,
       first_internal_date_ms = c.first_ms,
       last_internal_date_ms  = c.last_ms
  FROM (
        SELECT count(*)                AS cnt,
               min(internal_date_ms)   AS first_ms,
               max(internal_date_ms)   AS last_ms
          FROM src_gmail.message
         WHERE thread_id = %(thread_id)s
       ) c
 WHERE t.id = %(thread_id)s
RETURNING t.message_count, t.first_internal_date_ms, t.last_internal_date_ms
"""


def upsert_thread(
    conn: psycopg.Connection,
    *,
    tenant_id: UUID | str,
    connector_run_id: UUID | str,
    external_id: str,
    mailbox_id: UUID,
    is_synthetic: bool = False,
    observed_at: datetime | None = None,
    valid_from: datetime | None = None,
) -> UpsertResult:
    """Upsert one thread and recompute its rollup. ``external_id`` is the threadId.

    message_count, first_internal_date_ms and last_internal_date_ms are always
    derived from the thread's child message rows before this returns — never
    supplied by the caller and never incremented. On the initial insert there
    are no children yet (a message needs its thread_id to exist first), so the
    rollup lands at 0/NULL/NULL; call this again once the thread's messages are
    written and the real values appear.
    """
    params = _provenance(
        tenant_id=tenant_id,
        connector_run_id=connector_run_id,
        is_synthetic=is_synthetic,
        observed_at=observed_at,
        valid_from=valid_from,
    )
    params.update(external_id=external_id, mailbox_id=str(mailbox_id))
    result = _execute_upsert(conn, _THREAD_SQL, params)
    recompute_thread_rollup(conn, result.id)
    return result


def recompute_thread_rollup(
    conn: psycopg.Connection,
    thread_id: UUID,
) -> tuple[int, int | None, int | None]:
    """Recompute message_count and the date bounds from the thread's messages.

    Derived rather than incremented, so it is correct after a re-run, a partial
    run, or a backfill that arrives out of order. Returns the new
    ``(message_count, first_internal_date_ms, last_internal_date_ms)``.
    """
    with conn.cursor() as cur:
        cur.execute(_THREAD_ROLLUP_SQL, {"thread_id": str(thread_id)})
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"no such thread: {thread_id}")
    count, first_ms, last_ms = _columns(
        row, "message_count", "first_internal_date_ms", "last_internal_date_ms"
    )
    return int(count), first_ms, last_ms


# ── message ──────────────────────────────────────────────────────────────────

_MESSAGE_SQL = """
INSERT INTO src_gmail.message (
    tenant_id, source_system, external_id, thread_id, mailbox_id,
    subject, from_address, from_display_name, reply_to,
    to_addresses, cc_addresses,
    in_reply_to, references_header, list_id,
    body_text, body_html_present, quoted_stripped, signature_block,
    object_path, checksum_sha256,
    internal_date_ms, history_id, label_ids,
    is_synthetic, connector_run_id, observed_at, valid_from
) VALUES (
    %(tenant_id)s, %(source_system)s, %(external_id)s, %(thread_id)s, %(mailbox_id)s,
    %(subject)s, %(from_address)s, %(from_display_name)s, %(reply_to)s,
    %(to_addresses)s, %(cc_addresses)s,
    %(in_reply_to)s, %(references_header)s, %(list_id)s,
    %(body_text)s, %(body_html_present)s, %(quoted_stripped)s, %(signature_block)s,
    %(object_path)s, %(checksum_sha256)s,
    %(internal_date_ms)s, %(history_id)s, %(label_ids)s,
    %(is_synthetic)s, %(connector_run_id)s, %(observed_at)s, %(valid_from)s
)
ON CONFLICT (tenant_id, source_system, external_id) DO UPDATE SET
    thread_id         = EXCLUDED.thread_id,
    mailbox_id        = EXCLUDED.mailbox_id,
    subject           = EXCLUDED.subject,
    from_address      = EXCLUDED.from_address,
    from_display_name = EXCLUDED.from_display_name,
    reply_to          = EXCLUDED.reply_to,
    to_addresses      = EXCLUDED.to_addresses,
    cc_addresses      = EXCLUDED.cc_addresses,
    in_reply_to       = EXCLUDED.in_reply_to,
    references_header = EXCLUDED.references_header,
    list_id           = EXCLUDED.list_id,
    body_text         = EXCLUDED.body_text,
    body_html_present = EXCLUDED.body_html_present,
    quoted_stripped   = EXCLUDED.quoted_stripped,
    signature_block   = EXCLUDED.signature_block,
    object_path       = EXCLUDED.object_path,
    checksum_sha256   = EXCLUDED.checksum_sha256,
    internal_date_ms  = EXCLUDED.internal_date_ms,
    history_id        = EXCLUDED.history_id,
    label_ids         = EXCLUDED.label_ids,
    is_synthetic      = EXCLUDED.is_synthetic,
    connector_run_id  = EXCLUDED.connector_run_id,
    observed_at       = EXCLUDED.observed_at
RETURNING id, (xmax = 0) AS was_new
"""


@dataclass
class MessageRow:
    """Everything src_gmail.message stores for one Gmail message.

    Mirrors the ParsedMessage that Task 7's mime.py will produce, plus the two
    storage fields (object_path, checksum_sha256) that only the sync layer
    knows. Kept as a dataclass so the upsert signature stays readable.
    """

    external_id: str
    object_path: str
    checksum_sha256: str
    internal_date_ms: int
    subject: str | None = None
    from_address: str | None = None
    from_display_name: str | None = None
    reply_to: str | None = None
    to_addresses: list[str] = field(default_factory=list)
    cc_addresses: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
    references_header: str | None = None
    list_id: str | None = None
    body_text: str | None = None
    body_html_present: bool = False
    quoted_stripped: bool = False
    signature_block: str | None = None
    history_id: str | None = None
    label_ids: list[str] = field(default_factory=list)


def upsert_message(
    conn: psycopg.Connection,
    *,
    tenant_id: UUID | str,
    connector_run_id: UUID | str,
    thread_id: UUID,
    mailbox_id: UUID,
    message: MessageRow,
    is_synthetic: bool = False,
    observed_at: datetime | None = None,
    valid_from: datetime | None = None,
) -> UpsertResult:
    """Upsert one message. ``message.external_id`` is the Gmail messageId."""
    params = _provenance(
        tenant_id=tenant_id,
        connector_run_id=connector_run_id,
        is_synthetic=is_synthetic,
        observed_at=observed_at,
        valid_from=valid_from,
    )
    params.update(
        external_id=message.external_id,
        thread_id=str(thread_id),
        mailbox_id=str(mailbox_id),
        subject=message.subject,
        from_address=message.from_address,
        from_display_name=message.from_display_name,
        reply_to=message.reply_to,
        to_addresses=list(message.to_addresses),
        cc_addresses=list(message.cc_addresses),
        in_reply_to=message.in_reply_to,
        references_header=message.references_header,
        list_id=message.list_id,
        body_text=message.body_text,
        body_html_present=message.body_html_present,
        quoted_stripped=message.quoted_stripped,
        signature_block=message.signature_block,
        object_path=message.object_path,
        checksum_sha256=message.checksum_sha256,
        internal_date_ms=message.internal_date_ms,
        history_id=message.history_id,
        label_ids=list(message.label_ids),
    )
    return _execute_upsert(conn, _MESSAGE_SQL, params)


# ── attachment ───────────────────────────────────────────────────────────────

_ATTACHMENT_SQL = """
INSERT INTO src_gmail.attachment (
    tenant_id, source_system, external_id, message_id,
    filename, mime_type, size_bytes, object_path, checksum_sha256,
    is_synthetic, connector_run_id, observed_at, valid_from
) VALUES (
    %(tenant_id)s, %(source_system)s, %(external_id)s, %(message_id)s,
    %(filename)s, %(mime_type)s, %(size_bytes)s, %(object_path)s, %(checksum_sha256)s,
    %(is_synthetic)s, %(connector_run_id)s, %(observed_at)s, %(valid_from)s
)
ON CONFLICT (tenant_id, source_system, external_id) DO UPDATE SET
    message_id       = EXCLUDED.message_id,
    filename         = EXCLUDED.filename,
    mime_type        = EXCLUDED.mime_type,
    size_bytes       = EXCLUDED.size_bytes,
    object_path      = EXCLUDED.object_path,
    checksum_sha256  = EXCLUDED.checksum_sha256,
    is_synthetic     = EXCLUDED.is_synthetic,
    connector_run_id = EXCLUDED.connector_run_id,
    observed_at      = EXCLUDED.observed_at
RETURNING id, (xmax = 0) AS was_new
"""


def upsert_attachment(
    conn: psycopg.Connection,
    *,
    tenant_id: UUID | str,
    connector_run_id: UUID | str,
    message_id: UUID,
    external_id: str,
    object_path: str,
    checksum_sha256: str,
    filename: str | None = None,
    mime_type: str | None = None,
    size_bytes: int | None = None,
    is_synthetic: bool = False,
    observed_at: datetime | None = None,
    valid_from: datetime | None = None,
) -> UpsertResult:
    """Upsert one attachment. ``external_id`` is the Gmail attachmentId."""
    params = _provenance(
        tenant_id=tenant_id,
        connector_run_id=connector_run_id,
        is_synthetic=is_synthetic,
        observed_at=observed_at,
        valid_from=valid_from,
    )
    params.update(
        external_id=external_id,
        message_id=str(message_id),
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        object_path=object_path,
        checksum_sha256=checksum_sha256,
    )
    return _execute_upsert(conn, _ATTACHMENT_SQL, params)
