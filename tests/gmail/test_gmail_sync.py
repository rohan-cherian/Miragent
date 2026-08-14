"""Tests for Gmail ticket sync dedup + cursor + customer filter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from scout.gmail.client import GmailMessage
from scout.gmail.store import SyncState, TicketRow
from scout.gmail.sync import run_sync


@dataclass
class FakeStore:
    tickets: dict[str, TicketRow] = field(default_factory=dict)
    state: SyncState | None = None
    next_id: int = 1

    def ensure_schema(self) -> None:
        return

    def get_sync_state(self, mailbox: str) -> SyncState | None:
        if self.state and self.state.mailbox == mailbox:
            return self.state
        return None

    def upsert_sync_state(self, state: SyncState) -> None:
        self.state = state

    def insert_ticket(self, **kwargs: Any) -> TicketRow:
        mid = kwargs["gmail_message_id"]
        if mid in self.tickets:
            existing = self.tickets[mid]
            return TicketRow(**{**existing.__dict__, "inserted": False})
        row = TicketRow(
            ticket_id=self.next_id,
            gmail_message_id=mid,
            gmail_thread_id=kwargs["gmail_thread_id"],
            mailbox=kwargs["mailbox"],
            subject=kwargs["subject"],
            description=kwargs["description"],
            from_address=kwargs.get("from_address"),
            to_address=kwargs.get("to_address"),
            bookmark=kwargs.get("bookmark"),
            internal_date_ms=kwargs.get("internal_date_ms"),
            history_id=kwargs.get("history_id"),
            synced_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            inserted=True,
        )
        self.next_id += 1
        self.tickets[mid] = row
        return row

    def count_tickets(self, mailbox: str | None = None) -> int:
        if mailbox:
            return sum(1 for t in self.tickets.values() if t.mailbox == mailbox)
        return len(self.tickets)


class FakeClient:
    def __init__(self, messages: list[GmailMessage], history_id: str = "100") -> None:
        self._messages = messages
        self._history_id = history_id
        self.history_calls = 0
        self.last_q: str | None = None

    def get_profile(self) -> dict:
        return {"emailAddress": "motiveminds.itsupport@gmail.com", "historyId": self._history_id}

    def fetch_messages(self, *, max_results: int = 10, q: str | None = None) -> list[GmailMessage]:
        self.last_q = q
        return self._messages[:max_results]

    def fetch_messages_by_ids(self, message_ids: list[str]) -> list[GmailMessage]:
        by_id = {m.id: m for m in self._messages}
        return [by_id[i] for i in message_ids if i in by_id]

    def list_history_message_ids(self, *, start_history_id: str) -> tuple[list[str], str | None]:
        self.history_calls += 1
        return [], self._history_id


def _msg(
    mid: str,
    subject: str,
    ms: int,
    *,
    from_header: str = "user@example.com",
) -> GmailMessage:
    return GmailMessage(
        id=mid,
        thread_id=f"t-{mid}",
        history_id="50",
        internal_date_ms=ms,
        subject=subject,
        from_header=from_header,
        to_header="motiveminds.itsupport@gmail.com",
        snippet=subject,
        body_text=f"Body of {subject}",
        label_ids=("INBOX",),
    )


def test_sync_inserts_then_skips_duplicates():
    messages = [
        _msg("m1", "Password Issue", 1000, from_header="Vihaan <motiveminds.vihaan@gmail.com>"),
        _msg("m2", "Invoice", 2000, from_header="Jennifer <motiveminds.jennifer@gmail.com>"),
    ]
    store = FakeStore()
    client = FakeClient(messages)

    first = run_sync(client=client, store=store, mailbox="motiveminds.itsupport@gmail.com")
    assert first.inserted == 2
    assert first.skipped_duplicates == 0
    assert first.skipped_non_customer == 0
    assert store.state is not None
    assert store.state.last_message_id == "m2"
    assert client.last_q and "from:motiveminds.vihaan@gmail.com" in client.last_q

    store.state = None
    second = run_sync(client=client, store=store, mailbox="motiveminds.itsupport@gmail.com")
    assert second.inserted == 0
    assert second.skipped_duplicates == 2
    assert store.count_tickets() == 2


def test_sync_skips_non_customer_senders():
    messages = [
        _msg("m1", "Password Issue", 1000, from_header="Vihaan <motiveminds.vihaan@gmail.com>"),
        _msg("m2", "Noise", 1500, from_header="Rohan <rohancherian289@gmail.com>"),
        _msg("m3", "Google", 1600, from_header="Google <no-reply@google.com>"),
    ]
    store = FakeStore()
    client = FakeClient(messages)
    result = run_sync(client=client, store=store, mailbox="motiveminds.itsupport@gmail.com")
    assert result.inserted == 1
    assert result.skipped_non_customer == 2
    assert store.count_tickets() == 1


def test_sync_uses_history_when_cursor_present():
    messages = [
        _msg("m1", "Check", 1000, from_header="Ojasvi <motiveminds.ojasvi@gmail.com>"),
    ]
    store = FakeStore()
    store.state = SyncState(
        mailbox="motiveminds.itsupport@gmail.com",
        history_id="90",
        last_internal_date_ms=1000,
        last_message_id="m1",
    )
    client = FakeClient(messages, history_id="120")
    result = run_sync(client=client, store=store, mailbox="motiveminds.itsupport@gmail.com")
    assert result.mode == "history"
    assert client.history_calls == 1
    assert result.fetched == 0
    assert store.state.history_id == "120"
