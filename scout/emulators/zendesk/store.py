"""
In-memory Zendesk account state for the emulator.

Tickets are ordered by ``generated_timestamp`` (then ``id``) for incremental
export — matching real Zendesk, which compares ``start_time`` /
cursors against ``generated_timestamp``, not ``updated_at``.
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ticket_sort_key(ticket: dict[str, Any]) -> tuple[int, int]:
    return (int(ticket["generated_timestamp"]), int(ticket["id"]))


class ZendeskStore:
    """Thread-safe in-memory store for one emulated Zendesk account."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.tickets: dict[int, dict[str, Any]] = {}
        self.users: dict[int, dict[str, Any]] = {}
        self.organizations: dict[int, dict[str, Any]] = {}
        self._next_ticket_id = 1
        self.webhook_secret = "dGhpc19zZWNyZXRfaXNfZm9yX3Rlc3Rpbmdfb25seQ=="
        self.webhook_url: str | None = None
        self.emitted_webhooks: list[dict[str, Any]] = []
        self.account_id = 1

    def reset(self) -> None:
        """Clear all entities and webhook outbox."""
        with self._lock:
            self.tickets.clear()
            self.users.clear()
            self.organizations.clear()
            self.emitted_webhooks.clear()
            self._next_ticket_id = 1
            self.webhook_url = None
            self.webhook_secret = "dGhpc19zZWNyZXRfaXNfZm9yX3Rlc3Rpbmdfb25seQ=="

    def seed_defaults(self) -> None:
        """Load a small deterministic dataset suitable for pagination tests."""
        with self._lock:
            self.organizations = {
                1001: {
                    "id": 1001,
                    "name": "Acme Corp",
                    "domain_names": ["acme.example"],
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                },
                1002: {
                    "id": 1002,
                    "name": "Globex",
                    "domain_names": ["globex.example"],
                    "created_at": "2024-01-02T00:00:00Z",
                    "updated_at": "2024-01-02T00:00:00Z",
                },
            }
            self.users = {
                2001: {
                    "id": 2001,
                    "name": "Ada Agent",
                    "email": "ada@acme.example",
                    "role": "agent",
                    "organization_id": 1001,
                    "active": True,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                },
                2002: {
                    "id": 2002,
                    "name": "Ed Enduser",
                    "email": "ed@globex.example",
                    "role": "end-user",
                    "organization_id": 1002,
                    "active": True,
                    "created_at": "2024-01-02T00:00:00Z",
                    "updated_at": "2024-01-02T00:00:00Z",
                },
                2003: {
                    "id": 2003,
                    "name": "Admin Ann",
                    "email": "ann@acme.example",
                    "role": "admin",
                    "organization_id": 1001,
                    "active": True,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                },
            }

            base_ts = 1_700_000_000  # fixed epoch for deterministic tests
            tickets: dict[int, dict[str, Any]] = {}
            for i in range(1, 26):
                org_id = 1001 if i % 2 else 1002
                requester_id = 2002 if i % 2 == 0 else 2001
                assignee_id = 2001 if i % 3 else 2003
                ts = base_ts + i * 60
                tickets[i] = {
                    "id": i,
                    "url": f"/api/v2/tickets/{i}.json",
                    "subject": f"Ticket {i}",
                    "description": f"Body for ticket {i}",
                    "status": "open" if i % 5 else "pending",
                    "priority": "normal",
                    "type": "question",
                    "requester_id": requester_id,
                    "submitter_id": requester_id,
                    "assignee_id": assignee_id,
                    "organization_id": org_id,
                    "tags": [f"tag-{i % 3}"],
                    "created_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "generated_timestamp": ts,
                }
            self.tickets = tickets
            self._next_ticket_id = 26

    # ── Reads ────────────────────────────────────────────────────────────

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        with self._lock:
            ticket = self.tickets.get(ticket_id)
            return copy.deepcopy(ticket) if ticket else None

    def list_tickets_since(
        self,
        *,
        start_time: int | None = None,
        after_ts: int | None = None,
        after_id: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Tickets ordered by ``generated_timestamp``, then ``id``.

        - ``start_time``: inclusive lower bound on ``generated_timestamp``.
        - ``after_ts`` / ``after_id``: exclusive cursor position (resume after).
        - ``limit``: optional max rows (Postgres paging uses this).
        """
        with self._lock:
            items = sorted(self.tickets.values(), key=_ticket_sort_key)

        if start_time is not None:
            items = [t for t in items if int(t["generated_timestamp"]) >= start_time]

        if after_ts is not None and after_id is not None:
            items = [
                t
                for t in items
                if _ticket_sort_key(t) > (after_ts, after_id)
            ]

        if limit is not None:
            items = items[: max(0, int(limit))]

        return [copy.deepcopy(t) for t in items]

    def sideload_for_tickets(
        self,
        tickets: list[dict[str, Any]],
        include: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Return users / organizations referenced by ``tickets``."""
        extras: dict[str, list[dict[str, Any]]] = {}
        with self._lock:
            if "users" in include:
                user_ids: set[int] = set()
                for t in tickets:
                    for key in ("requester_id", "submitter_id", "assignee_id"):
                        uid = t.get(key)
                        if uid is not None:
                            user_ids.add(int(uid))
                extras["users"] = [
                    copy.deepcopy(self.users[uid])
                    for uid in sorted(user_ids)
                    if uid in self.users
                ]
            if "organizations" in include:
                org_ids = {
                    int(t["organization_id"])
                    for t in tickets
                    if t.get("organization_id") is not None
                }
                extras["organizations"] = [
                    copy.deepcopy(self.organizations[oid])
                    for oid in sorted(org_ids)
                    if oid in self.organizations
                ]
        return extras

    # ── Writes ───────────────────────────────────────────────────────────

    def update_ticket(
        self,
        ticket_id: int,
        patch: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """
        Apply a ticket update. Bumps ``updated_at`` and ``generated_timestamp``.

        Returns the updated ticket, or ``None`` if missing.
        """
        now = time.time() if now is None else now
        with self._lock:
            existing = self.tickets.get(ticket_id)
            if existing is None:
                return None

            # Zendesk wraps writable fields under ticket; ignore read-only keys.
            readonly = {"id", "url", "created_at", "generated_timestamp"}
            for key, value in patch.items():
                if key in readonly:
                    continue
                existing[key] = value

            existing["updated_at"] = datetime.fromtimestamp(
                now, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Real Zendesk advances generated_timestamp on every system update.
            existing["generated_timestamp"] = int(now)
            self.tickets[ticket_id] = existing
            return copy.deepcopy(existing)

    def record_webhook(self, delivery: dict[str, Any]) -> None:
        with self._lock:
            self.emitted_webhooks.append(delivery)
