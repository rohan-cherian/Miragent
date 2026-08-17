"""
Gmail -> MinIO raw bucket ingestion.

Takes EVERY message in the mailbox (no sender filter — that is the ticket
sync's job, in scout/gmail/sync.py) and writes one self-contained JSON
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from scout.config import settings
from scout.gmail.client import GmailClient
from scout.gmail.envelope import (
    build_attachment_entry,
    build_envelope,
    collect_attachment_specs,
    serialise,
)
from scout.gmail.raw_ledger import GmailRawLedger, RawSyncState
from scout.raw.keys import InvalidMessageId, build_object_key, partition_date
from scout.raw.minio_client import RawLakeClient

logger = logging.getLogger(__name__)


@dataclass
class RawSyncResult:
    account_id: str
    mode: str = "backfill"  # backfill | history
    discovered: int = 0
    written: int = 0
    skipped_duplicates: int = 0  # HEAD said the object is already there
    skipped_known: int = 0  # ledger pre-filter, no API call spent
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
    ) -> None:
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
        self._pending_backfill_token: str | None = None

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
                logger.warning("Gmail historyId expired — falling back to full list")

        # Backfill: walk the whole mailbox, resuming from a stored page token.
        result.mode = "backfill"
        page_token = state.backfill_page_token if state else None
        last_token: str | None = None
        seen: set[str] = set()
        candidates: list[str] = []
        for mid, next_token in self.client.iter_all_message_ids(
            q=self.query or None,
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
        self, message_id: str, raw_message: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Fetch every attachment's bytes and inline them base64.

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
            entries.append(
                build_attachment_entry(
                    spec, raw_bytes, max_bytes=self.max_attachment_bytes, error=error
                )
            )
        return entries

    def ingest_message(self, message_id: str, result: RawSyncResult) -> bool:
        """Write one message. Returns True when an object was PUT."""
        raw_message = self.client.get_message(message_id, format="full")

        # Section 16: malformed data is skipped and logged, never written under
        # a broken or blank name.
        payload_id = (raw_message.get("id") or "").strip()
        if not payload_id:
            result.skipped_malformed += 1
            self._note_skip(message_id, "malformed", "Gmail response has no message id")
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

        attachments = self._hydrate_attachments(payload_id, raw_message)
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

        result.written += 1
        result.bytes_written += put.size_bytes
        result.attachments_written += sum(1 for a in attachments if a.get("data_base64"))
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

        profile = self.client.get_profile()
        profile_history = str(profile.get("historyId") or "") or None
        state = self.ledger.get_state(self.account_id) if self.ledger else None

        candidates = self._discover(state, result)
        result.discovered = len(candidates)

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

        for message_id in todo:
            try:
                self.ingest_message(message_id, result)
            except Exception as exc:
                message = f"{message_id}: {type(exc).__name__}: {exc}"
                result.failed += 1
                result.errors.append(message)
                # Not marked stored, so the next run retries it (section 16).
                logger.exception("Failed to ingest %s", message_id)

        backfill_done = result.backfill_done or bool(state and state.backfill_done)
        # Only advance the history cursor once the backfill has walked the whole
        # mailbox. Advancing early would strand every message older than the
        # cursor, permanently unreachable by the incremental path.
        next_history = (
            (result.history_id or profile_history)
            if backfill_done
            else (state.history_id if state else None)
        )
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
