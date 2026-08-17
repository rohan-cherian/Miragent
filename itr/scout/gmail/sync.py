"""
Gmail -> MinIO raw bucket ingestion.

Takes EVERY message in the mailbox and writes one self-contained JSON
document per email to ``raw/gmail/YYYY/MM/DD/email_<message_id>.json``.

Duplicate handling follows handover doc section 8: the object key is fully
derived from the Gmail message ID, so a HEAD (``stat_object``) on that exact
path before the PUT is the duplicate check.

  1. Discover candidate message ids (history cursor, or a full list backfill).
  2. Drop ids the ledger has already recorded — an optimisation that saves a
     Gmail call, NOT the correctness guarantee.
  3. Fetch the message; derive the key from its id and received date.
  4. HEAD the key. Exists -> skip and log. Missing -> PUT.
  5. Record it in the ledger for audit.

Because the key is deterministic, two syncers racing the same message write
identical bytes to the same key. There is no interleaving that yields two
objects for one email.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, TypeVar

import httpx

from scout.config import settings
from scout.gmail.client import GmailClient
from scout.gmail.customers import (
    extract_email_address,
    gmail_from_query,
    is_customer_sender,
    parse_sender_list,
)
from scout.gmail.envelope import (
    build_attachment_entry,
    build_envelope,
    collect_attachment_specs,
    serialise,
)
from scout.gmail.mime import parse_message
from scout.gmail.raw_ledger import GmailRawLedger, RawSyncState
from scout.gmail.store import (
    MessageRow,
    upsert_attachment,
    upsert_mailbox,
    upsert_message,
    upsert_thread,
)
from scout.raw.keys import (
    InvalidMessageId,
    build_attachment_key,
    build_object_key,
    partition_date,
)
from scout.raw.minio_client import RawLakeClient
from scout.raw.runs import connector_run

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RATE_LIMIT_STATUS = {429, 403}  # Gmail signals quota with either
_GMAIL_RETRIES = 4
_GMAIL_BASE_DELAY = 1.0


def gmail_retry(what: str, fn: Callable[[], T]) -> T:
    """Call Gmail, retrying rate limits with exponential backoff and jitter.

    Jitter matters more than the backoff itself here: without it, every worker
    throttled at the same moment retries at the same moment and the quota is
    hit again in lockstep.
    """
    delay = _GMAIL_BASE_DELAY
    for attempt in range(1, _GMAIL_RETRIES + 1):
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in _RATE_LIMIT_STATUS or attempt == _GMAIL_RETRIES:
                raise
            sleep_for = delay + random.uniform(0, delay / 2)
            logger.warning(
                "Gmail %s rate-limited (%s), attempt %d/%d, sleeping %.1fs",
                what,
                status,
                attempt,
                _GMAIL_RETRIES,
                sleep_for,
            )
            time.sleep(sleep_for)
            delay *= 2
    raise RuntimeError(f"unreachable: {what}")  # pragma: no cover


@dataclass
class RawSyncResult:
    account_id: str
    mode: str = "backfill"  # backfill | history
    discovered: int = 0
    written: int = 0
    skipped_duplicates: int = 0  # HEAD said the object is already there
    skipped_known: int = 0  # ledger pre-filter, no API call spent
    skipped_non_customer: int = 0  # sender not on the allowlist
    skipped_malformed: int = 0
    failed: int = 0
    attachments_written: int = 0
    bytes_written: int = 0
    history_id: str | None = None
    backfill_done: bool = False
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"mode={self.mode} discovered={self.discovered} "
            f"written={self.written} "
            f"dupes_skipped={self.skipped_known + self.skipped_duplicates} "
            f"non_customer={self.skipped_non_customer} "
            f"malformed={self.skipped_malformed} failed={self.failed} "
            f"attachments={self.attachments_written} bytes={self.bytes_written}"
        )


class GmailRawSync:
    """Orchestrates Gmail -> raw lake ingestion for one mailbox."""

    def __init__(
        self,
        *,
        client: GmailClient,
        lake: RawLakeClient,
        account_id: str,
        ledger: GmailRawLedger | None = None,
        prefix: str | None = None,
        layout: str | None = None,
        partition_by: str | None = None,
        object_pattern: str | None = None,
        max_attachment_bytes: int | None = None,
        max_per_run: int | None = None,
        include_spam_trash: bool | None = None,
        query: str | None = None,
        page_size: int | None = None,
        use_ledger_prefilter: bool = True,
        customer_only: bool | None = None,
        customer_senders: str | None = None,
        run_store: Any = None,
    ) -> None:
        # Injectable so tests exercise the real connector_run flow without
        # Postgres; production leaves it None and it is built from the ledger.
        self.run_store = run_store
        self.client = client
        self.lake = lake
        self.ledger = ledger
        self.account_id = account_id
        self.prefix = prefix if prefix is not None else settings.gmail_raw_prefix
        self.layout = layout or settings.gmail_raw_path_layout
        self.partition_by = partition_by or settings.gmail_raw_partition_by
        self.object_pattern = object_pattern or settings.gmail_raw_object_pattern
        self.max_attachment_bytes = (
            max_attachment_bytes
            if max_attachment_bytes is not None
            else settings.gmail_raw_max_attachment_bytes
        )
        self.max_per_run = (
            max_per_run if max_per_run is not None else settings.gmail_raw_max_per_run
        )
        self.include_spam_trash = (
            include_spam_trash
            if include_spam_trash is not None
            else settings.gmail_raw_include_spam_trash
        )
        self.query = query if query is not None else settings.gmail_raw_query
        self.page_size = page_size or settings.gmail_raw_page_size
        self.use_ledger_prefilter = use_ledger_prefilter
        self.customer_only = (
            customer_only if customer_only is not None else settings.gmail_customer_only
        )
        self.allowed_senders = parse_sender_list(
            customer_senders
            if customer_senders is not None
            else settings.gmail_customer_senders
        )
        self._pending_backfill_token: str | None = None
        self._run: Any = None
        self._upsert_failed = False

    # ── key building ──────────────────────────────────────────────────────────

    def object_key_for(self, message_id: str, internal_date_ms: int | None) -> str:
        return build_object_key(
            partition=partition_date(
                internal_date_ms=internal_date_ms, partition_by=self.partition_by
            ),
            message_id=message_id,
            prefix=self.prefix,
            layout=self.layout,
            account_id=self.account_id,
            pattern=self.object_pattern,
        )

    def _heal_ledger(
        self,
        message_id: str,
        raw_message: dict[str, Any],
        key: str,
        internal_ms: int | None,
        stat: dict[str, Any],
    ) -> None:
        """
        Backfill an audit row for an object the bucket has but the ledger does
        not — e.g. after the ledger was wiped, or a crash between PUT and
        record. Without this the pre-filter stays permanently cold and the
        audit trail under-reports what is actually stored.

        The values come from the metadata stamped on the object at write time,
        so healing costs one HEAD and no body read.
        """
        if self.ledger is None:
            return
        try:
            if self.ledger.get(self.account_id, message_id) is not None:
                return
            meta = stat.get("metadata") or {}
            self.ledger.record_written(
                account_id=self.account_id,
                gmail_message_id=message_id,
                gmail_thread_id=raw_message.get("threadId"),
                object_key=key,
                partition=partition_date(
                    internal_date_ms=internal_ms, partition_by=self.partition_by
                ),
                content_sha256=meta.get("content-sha256") or "",
                size_bytes=int(stat.get("size_bytes") or 0),
                internal_date_ms=internal_ms,
                attachment_count=int(meta.get("attachment-count") or 0),
            )
            logger.info("Healed missing ledger row for %s", key)
        except Exception:  # bookkeeping must never break ingestion
            logger.exception("Could not heal ledger row for %s", key)

    def upsert_canonical(
        self,
        *,
        raw_message: dict[str, Any],
        object_path: str,
        checksum_sha256: str,
        attachments: list[dict[str, Any]],
        internal_ms: int | None,
        connector_run_id: str,
    ) -> bool:
        """Step 5 of the doc's order: upsert into src_gmail.

        Stores only the object path and the checksum — never the payload. The
        bytes stay in MinIO, which is what makes replay and audit possible.

        One transaction per message: mailbox -> thread -> message -> attachments,
        committed together. The caller checkpoints the cursor only after this
        returns, because a crash between the two would lose the message
        permanently.
        """
        if self.ledger is None or not hasattr(self.ledger, "connect"):
            # No Postgres behind this sync (unit tests, dry runs). Not a
            # failure — there is simply nowhere to upsert.
            return False

        # Step 4 of the doc's order: parse MIME. Task 7's parser owns every
        # field below, including the three the raw envelope cannot give —
        # from_display_name, quoted_stripped and signature_block.
        parsed = parse_message(raw_message)
        row = MessageRow(
            external_id=parsed.external_id,
            object_path=object_path,
            checksum_sha256=checksum_sha256,
            internal_date_ms=int(parsed.internal_date_ms or internal_ms or 0),
            subject=parsed.subject,
            from_address=parsed.from_address,
            from_display_name=parsed.from_display_name,
            reply_to=parsed.reply_to,
            to_addresses=parsed.to_addresses,
            cc_addresses=parsed.cc_addresses,
            in_reply_to=parsed.in_reply_to,
            references_header=parsed.references_header,
            list_id=parsed.list_id,
            body_text=parsed.body_text or None,
            body_html_present=parsed.body_html_present,
            quoted_stripped=parsed.quoted_stripped,
            signature_block=parsed.signature_block,
            history_id=parsed.history_id,
            label_ids=parsed.label_ids,
        )
        tenant = settings.tenant_id
        with self.ledger.connect() as conn:
            mailbox = upsert_mailbox(
                conn,
                tenant_id=tenant,
                connector_run_id=connector_run_id,
                external_id=self.account_id,
                address=self.account_id,
            )
            thread = upsert_thread(
                conn,
                tenant_id=tenant,
                connector_run_id=connector_run_id,
                external_id=parsed.thread_external_id,
                mailbox_id=mailbox.id,
            )
            message = upsert_message(
                conn,
                tenant_id=tenant,
                connector_run_id=connector_run_id,
                thread_id=thread.id,
                mailbox_id=mailbox.id,
                message=row,
            )
            for att in attachments:
                if not att.get("object_path"):
                    continue  # oversized or failed: no object to point at
                upsert_attachment(
                    conn,
                    tenant_id=tenant,
                    connector_run_id=connector_run_id,
                    message_id=message.id,
                    external_id=str(att.get("attachment_id") or att.get("part_id") or ""),
                    object_path=str(att["object_path"]),
                    checksum_sha256=str(att.get("sha256") or ""),
                    filename=att.get("filename") or None,
                    mime_type=att.get("mime_type") or None,
                    size_bytes=int(att.get("size_bytes") or 0),
                )
            # Refresh the thread rollup now its children exist.
            upsert_thread(
                conn,
                tenant_id=tenant,
                connector_run_id=connector_run_id,
                external_id=parsed.thread_external_id,
                mailbox_id=mailbox.id,
            )
            conn.commit()
        return True

    def _note_skip(self, message_id: str | None, reason: str, detail: str = "") -> None:
        logger.info("Skipping %s: %s %s", message_id, reason, detail)
        if self.ledger is None:
            return
        try:
            self.ledger.record_skipped(
                account_id=self.account_id,
                gmail_message_id=message_id,
                reason=reason,
                detail=detail,
            )
        except Exception:  # bookkeeping must never break ingestion
            logger.exception("Could not record skip for %s", message_id)

    # ── customer allowlist ────────────────────────────────────────────────────

    def _listing_query(self) -> str | None:
        """
        Gmail search string for the backfill listing.

        The allowlist is pushed server-side so a backfill never downloads mail
        it would only discard. History mode cannot do this — ``history.list``
        takes no query — so that path filters after fetch instead.
        """
        parts = [p for p in (self.query or "").strip().split() if p]
        if self.customer_only:
            clause = gmail_from_query(self.allowed_senders)
            if clause:
                parts.append(clause)
        return " ".join(parts) if parts else None

    def _is_customer(self, raw_message: dict[str, Any]) -> tuple[bool, str]:
        """(allowed, sender_address) for one fetched message."""
        headers = (raw_message.get("payload") or {}).get("headers") or []
        from_header = next(
            (h.get("value", "") for h in headers if str(h.get("name", "")).lower() == "from"),
            "",
        )
        sender = extract_email_address(from_header) or "(unknown)"
        if not self.customer_only:
            return True, sender
        return is_customer_sender(from_header, self.allowed_senders), sender

    # ── discovery ─────────────────────────────────────────────────────────────

    def _discover(self, state: RawSyncState | None, result: RawSyncResult) -> list[str]:
        """Candidate message ids for this run, newest-first."""
        budget = self.max_per_run

        if state and state.history_id and state.backfill_done:
            try:
                ids, newest = self.client.list_history_message_ids(
                    start_history_id=state.history_id
                )
                result.mode = "history"
                result.history_id = newest
                result.backfill_done = True
                return ids[:budget]
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise
                # Gmail drops historyIds after about a week. Falling back to a
                # full backfill is the only way to recover — crashing here
                # would strand the mailbox until someone intervened.
                logger.warning("Gmail historyId expired — falling back to full list")
                if self._run is not None:
                    self._run.note_error(
                        "history_id_expired",
                        start_history_id=state.history_id,
                        action="fell back to full backfill",
                    )

        # Backfill: walk the mailbox, resuming from a stored page token.
        result.mode = "backfill"
        page_token = state.backfill_page_token if state else None
        last_token: str | None = None
        seen: set[str] = set()
        candidates: list[str] = []
        for mid, next_token in self.client.iter_all_message_ids(
            q=self._listing_query(),
            include_spam_trash=self.include_spam_trash,
            page_size=self.page_size,
            limit=budget,
            start_page_token=page_token,
        ):
            last_token = next_token
            if mid not in seen:
                seen.add(mid)
                candidates.append(mid)

        self._pending_backfill_token = last_token
        result.backfill_done = last_token is None
        return candidates

    # ── per-message write ─────────────────────────────────────────────────────

    def _hydrate_attachments(
        self,
        message_id: str,
        raw_message: dict[str, Any],
        partition: date | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch every attachment's bytes and store each as its own raw object.

        Slice-1 doc Task 6 keeps attachments beside their message rather than
        base64 inside the message JSON, so ``src_gmail.attachment.object_path``
        has a real path to point at. Each entry records that path plus sha256.

        Parts Gmail already inlined in ``body.data`` cost no extra call. A
        single attachment failing does not fail the message — the entry keeps
        its metadata and records the error.
        """
        entries: list[dict[str, Any]] = []
        for spec in collect_attachment_specs(raw_message.get("payload") or {}):
            size = int(spec.get("size_bytes") or 0)
            if size > self.max_attachment_bytes:
                entries.append(
                    build_attachment_entry(spec, None, max_bytes=self.max_attachment_bytes)
                )
                continue

            raw_bytes: bytes | None = None
            error: str | None = None
            try:
                if spec.get("inline_data"):
                    from scout.gmail.envelope import b64url_to_bytes

                    raw_bytes = b64url_to_bytes(str(spec["inline_data"]))
                elif spec.get("attachment_id"):
                    raw_bytes = self.client.get_attachment_bytes(
                        message_id=message_id,
                        attachment_id=str(spec["attachment_id"]),
                    )
                else:
                    raw_bytes = b""
            except Exception as exc:  # keep the message, flag the attachment
                error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Attachment fetch failed (message=%s file=%s): %s",
                    message_id,
                    spec.get("filename"),
                    error,
                )
            # Store the bytes as their own object, then point the entry at it.
            object_path: str | None = None
            if raw_bytes and len(raw_bytes) <= self.max_attachment_bytes:
                try:
                    object_path = self.lake.put_raw(
                        raw_bytes,
                        build_attachment_key(
                            partition=partition or date.today(),
                            message_id=message_id,
                            attachment_id=str(spec.get("attachment_id") or spec.get("part_id") or ""),
                            filename=str(spec.get("filename") or ""),
                            prefix=self.prefix,
                            layout=self.layout,
                            account_id=self.account_id,
                        ),
                        content_type=str(spec.get("mime_type") or "application/octet-stream"),
                    )
                except Exception as exc:  # keep the message, flag the attachment
                    error = error or f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Attachment store failed (message=%s file=%s): %s",
                        message_id,
                        spec.get("filename"),
                        error,
                    )
            entries.append(
                build_attachment_entry(
                    spec,
                    raw_bytes,
                    max_bytes=self.max_attachment_bytes,
                    object_path=object_path,
                    error=error,
                )
            )
        return entries

    def ingest_message(self, message_id: str, result: RawSyncResult) -> bool:
        """Write one message. Returns True when an object was PUT."""
        raw_message = gmail_retry(
            f"get_message {message_id}",
            lambda: self.client.get_message(message_id, format="full"),
        )

        # Section 16: malformed data is skipped and logged, never written under
        # a broken or blank name.
        payload_id = (raw_message.get("id") or "").strip()
        if not payload_id:
            result.skipped_malformed += 1
            self._note_skip(message_id, "malformed", "Gmail response has no message id")
            return False

        # Customer allowlist. The backfill listing is already filtered
        # server-side; this catches the history path, which cannot be.
        allowed, sender = self._is_customer(raw_message)
        if not allowed:
            result.skipped_non_customer += 1
            self._note_skip(payload_id, "non_customer", f"from {sender}")
            return False

        internal_raw = raw_message.get("internalDate")
        internal_ms = int(internal_raw) if internal_raw is not None else None

        try:
            key = self.object_key_for(payload_id, internal_ms)
        except InvalidMessageId as exc:
            result.skipped_malformed += 1
            self._note_skip(payload_id, "invalid_message_id", str(exc))
            return False

        # Section 8: HEAD the derived path. This is the duplicate check.
        stat = self.lake.stat_object(key)
        if stat is not None:
            result.skipped_duplicates += 1
            logger.info("Duplicate, already in bucket: %s -> %s", payload_id, key)
            self._heal_ledger(payload_id, raw_message, key, internal_ms, stat)
            return False

        # Same day folder as the message, so the two never drift apart.
        partition = partition_date(
            internal_date_ms=internal_ms, partition_by=self.partition_by
        )
        attachments = self._hydrate_attachments(payload_id, raw_message, partition)
        document = build_envelope(
            raw_message,
            account_id=self.account_id,
            attachments=attachments,
        )
        body = serialise(document)

        put = self.lake.put_bytes(
            key=key,
            body=body,
            content_type="application/json",
            metadata={
                "gmail-message-id": payload_id,
                "gmail-thread-id": str(raw_message.get("threadId") or ""),
                "account-id": self.account_id,
                "content-sha256": document["content_sha256"],
                "attachment-count": str(len(attachments)),
            },
        )

        if self.ledger is not None:
            try:
                self.ledger.record_written(
                    account_id=self.account_id,
                    gmail_message_id=payload_id,
                    gmail_thread_id=raw_message.get("threadId"),
                    object_key=key,
                    partition=partition_date(
                        internal_date_ms=internal_ms, partition_by=self.partition_by
                    ),
                    content_sha256=document["content_sha256"],
                    size_bytes=put.size_bytes,
                    internal_date_ms=internal_ms,
                    attachment_count=len(attachments),
                )
            except Exception:
                # The object is safely in the bucket; a missing audit row only
                # costs one redundant HEAD next run.
                logger.exception("Wrote %s but could not record it in the ledger", key)

        # Step 5: canonical upsert. Only the path and checksum, never the bytes.
        if self._run is not None:
            try:
                self.upsert_canonical(
                    raw_message=raw_message,
                    object_path=key,
                    checksum_sha256=document["content_sha256"],
                    attachments=attachments,
                    internal_ms=internal_ms,
                    connector_run_id=str(self._run.id),
                )
            except Exception as exc:
                # The object is in the bucket, so nothing is lost — but the
                # cursor must not advance past a message that never reached
                # src_gmail, or the incremental path would skip it forever.
                self._upsert_failed = True
                result.errors.append(f"{payload_id}: upsert failed: {exc}")
                logger.exception("Wrote %s but could not upsert into src_gmail", key)

        result.written += 1
        result.bytes_written += put.size_bytes
        result.attachments_written += sum(1 for a in attachments if a.get("object_path"))
        logger.info(
            "Wrote %s -> s3://%s/%s (%d bytes, %d attachment(s))",
            payload_id,
            self.lake.bucket,
            key,
            put.size_bytes,
            len(attachments),
        )
        return True

    # ── entry point ───────────────────────────────────────────────────────────

    def run(self) -> RawSyncResult:
        result = RawSyncResult(account_id=self.account_id)
        self._pending_backfill_token = None
        self._upsert_failed = False

        state = self.ledger.get_state(self.account_id) if self.ledger else None
        # The mode the run will take, known before discovery so the runs row is
        # accurate from the moment it is inserted.
        expected_mode = (
            "history" if (state and state.history_id and state.backfill_done) else "backfill"
        )
        run_ctx = connector_run(
            "gmail",
            expected_mode,
            state.history_id if state else None,
            database_url=getattr(self.ledger, "database_url", None),
            store=self.run_store,
        )
        with run_ctx as run:
            self._run = run
            try:
                return self._run_stages(result, state, run)
            finally:
                self._run = None

    def _run_stages(self, result, state, run) -> RawSyncResult:
        """The seven pipeline stages, in order, with running counts.

        Four of them — redact, normalise, resolve, index — have no work yet
        (Tasks 12, 13, 14 and 17). They still emit, because the console's
        Pipeline Scan screen renders all seven and a missing stage reads as a
        broken pipeline rather than an unbuilt one.
        """
        profile = gmail_retry("get_profile", self.client.get_profile)
        profile_history = str(profile.get("historyId") or "") or None
        run.stage("connect", 100, f"Connected to Gmail as {self.account_id}")

        candidates = self._discover(state, result)
        result.discovered = len(candidates)
        run.messages_seen = len(candidates)
        run.stage(
            "discover",
            100,
            f"Discovered {len(candidates)} message(s) in {result.mode} mode",
        )

        todo = candidates
        if self.ledger is not None and self.use_ledger_prefilter and candidates:
            known = self.ledger.already_written(self.account_id, candidates)
            todo = [m for m in candidates if m not in known]
            result.skipped_known = len(known)

        if todo:
            logger.info(
                "Gmail raw sync: %d candidate(s), %d to check, %d known",
                len(candidates),
                len(todo),
                result.skipped_known,
            )

        for index, message_id in enumerate(todo, start=1):
            try:
                self.ingest_message(message_id, result)
            except Exception as exc:
                message = f"{message_id}: {type(exc).__name__}: {exc}"
                result.failed += 1
                result.errors.append(message)
                run.note_drop(message_id, f"{type(exc).__name__}: {exc}")
                # Not marked stored, so the next run retries it (section 16).
                logger.exception("Failed to ingest %s", message_id)
            if todo and index % 25 == 0:
                run.stage(
                    "extract",
                    int(index * 100 / len(todo)),
                    f"Extracted {result.written} of {len(todo)} message(s) to the raw lake",
                )

        run.messages_written = result.written
        run.messages_skipped = (
            result.skipped_known
            + result.skipped_duplicates
            + result.skipped_non_customer
            + result.skipped_malformed
        )
        run.stage(
            "extract",
            100,
            f"Extracted {result.written} new message(s), "
            f"{result.skipped_known + result.skipped_duplicates} already stored, "
            f"{result.attachments_written} attachment(s) written",
        )
        run.stage("redact", 100, "PII redaction not wired in Slice 1 (Task 12): 0 documents masked")
        run.stage(
            "normalise",
            100,
            f"Replicated {result.written} message(s) into src_gmail (Task 13 canonicalises)",
        )
        run.stage("resolve", 100, "Identity resolution pending (Task 14): 0 people matched")
        run.stage("index", 100, "Embedding and indexing pending (Task 17): 0 chunks indexed")

        backfill_done = result.backfill_done or bool(state and state.backfill_done)
        # Only advance the history cursor once the backfill has walked the whole
        # mailbox. Advancing early would strand every message older than the
        # cursor, permanently unreachable by the incremental path.
        next_history = (
            (result.history_id or profile_history)
            if backfill_done
            else (state.history_id if state else None)
        )
        # A message that reached MinIO but not src_gmail must not be cursored
        # past, or the incremental path would never look at it again.
        if self._upsert_failed:
            logger.warning("Holding the cursor: at least one src_gmail upsert failed")
            next_history = state.history_id if state else None
        if self.ledger is not None:
            self.ledger.save_state(
                RawSyncState(
                    account_id=self.account_id,
                    history_id=next_history,
                    backfill_done=backfill_done,
                    backfill_page_token=None
                    if backfill_done
                    else self._pending_backfill_token,
                    last_synced_at=datetime.now(timezone.utc),
                    watch_expiration_ms=state.watch_expiration_ms if state else None,
                )
            )
        result.history_id = next_history
        result.backfill_done = backfill_done
        run.cursor_after = next_history
        return result


def build_raw_sync(
    *,
    client: GmailClient | None = None,
    ledger: GmailRawLedger | None = None,
    lake: RawLakeClient | None = None,
    account_id: str | None = None,
) -> GmailRawSync:
    """Wire a sync from settings, resolving the mailbox from the Gmail profile."""
    from scout.gmail.auth import GmailTokenStore

    gmail = client or GmailClient(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token_store=GmailTokenStore(settings.gmail_token_path),
        user_id="me",
        refresh_token_fallback=settings.gmail_refresh_token,
    )
    resolved = account_id
    if not resolved:
        profile = gmail.get_profile()
        resolved = (profile.get("emailAddress") or settings.gmail_user or "me").strip()

    return GmailRawSync(
        client=gmail,
        ledger=ledger or GmailRawLedger(settings.gmail_database_url),
        lake=lake or RawLakeClient(),
        account_id=resolved,
    )
