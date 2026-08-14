"""
Gmail → Postgres ticket sync (Phases 5–6).

- Dedup on ``gmail_message_id`` (UNIQUE)
- Cursor in ``src_gmail.sync_state`` (history_id + last_internal_date_ms)
- First run bootstraps recent mail; later runs prefer ``history.list``
- Only messages From allowlisted customer addresses become tickets
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from scout.config import settings
from scout.gmail.client import GmailClient, GmailMessage
from scout.gmail.customers import (
    gmail_from_query,
    is_customer_sender,
    parse_sender_list,
)
from scout.gmail.store import GmailTicketStore, SyncState

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    mailbox: str
    fetched: int = 0
    inserted: int = 0
    skipped_duplicates: int = 0
    skipped_non_customer: int = 0
    history_id: str | None = None
    mode: str = "list"  # list | history
    errors: list[str] = field(default_factory=list)


def run_sync(
    *,
    client: GmailClient,
    store: GmailTicketStore,
    mailbox: str,
    bootstrap_max: int = 100,
    customer_senders: str | None = None,
) -> SyncResult:
    """
    Pull new Gmail messages and insert tickets for customer senders only.

    ``mailbox`` should be the profile email address (for sync_state key).
    ``customer_senders`` overrides ``settings.gmail_customer_senders`` when set.
    """
    store.ensure_schema()
    allowed = parse_sender_list(
        customer_senders if customer_senders is not None else settings.gmail_customer_senders
    )
    result = SyncResult(mailbox=mailbox)
    profile = client.get_profile()
    profile_history = str(profile.get("historyId") or "") or None
    state = store.get_sync_state(mailbox)

    messages: list[GmailMessage] = []
    if state and state.history_id:
        try:
            ids, hist = client.list_history_message_ids(start_history_id=state.history_id)
            result.mode = "history"
            if hist:
                profile_history = hist
            if ids:
                messages = client.fetch_messages_by_ids(ids)
            logger.info("Gmail history sync: %s new message id(s)", len(ids))
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning("Gmail historyId expired — falling back to list sync")
                messages = _bootstrap_list(client, bootstrap_max, result, allowed)
            else:
                raise
    else:
        messages = _bootstrap_list(client, bootstrap_max, result, allowed)

    result.fetched = len(messages)
    max_internal: int | None = state.last_internal_date_ms if state else None
    last_message_id = state.last_message_id if state else None

    for msg in messages:
        if not is_customer_sender(msg.from_header, allowed):
            result.skipped_non_customer += 1
            logger.debug(
                "Skipping non-customer sender: %s (%s)",
                msg.from_header,
                msg.id,
            )
            continue

        bookmark = f"gmail:{msg.id}"
        row = store.insert_ticket(
            mailbox=mailbox,
            gmail_message_id=msg.id,
            gmail_thread_id=msg.thread_id,
            subject=msg.subject,
            description=msg.body_text or msg.snippet or "",
            from_address=msg.from_header,
            to_address=msg.to_header,
            bookmark=bookmark,
            internal_date_ms=msg.internal_date_ms,
            history_id=msg.history_id,
        )
        if row.inserted:
            result.inserted += 1
        else:
            result.skipped_duplicates += 1

        if msg.internal_date_ms is not None:
            if max_internal is None or msg.internal_date_ms >= max_internal:
                max_internal = msg.internal_date_ms
                last_message_id = msg.id

    store.upsert_sync_state(
        SyncState(
            mailbox=mailbox,
            history_id=profile_history or (state.history_id if state else None),
            last_internal_date_ms=max_internal,
            last_message_id=last_message_id,
            last_synced_at=datetime.now(timezone.utc),
        )
    )
    result.history_id = profile_history
    return result


def _bootstrap_list(
    client: GmailClient,
    bootstrap_max: int,
    result: SyncResult,
    allowed: frozenset[str],
) -> list[GmailMessage]:
    result.mode = "list"
    q = gmail_from_query(allowed)
    logger.info("Gmail list sync query: %s", q)
    return client.fetch_messages(max_results=bootstrap_max, q=q)
