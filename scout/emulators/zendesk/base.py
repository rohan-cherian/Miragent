"""Shared store protocol for Zendesk emulator backends (memory / Postgres)."""

from __future__ import annotations

from typing import Any, Protocol


class TicketStore(Protocol):
    """Read/write surface used by export, routes, and webhooks."""

    webhook_secret: str
    webhook_url: str | None
    emitted_webhooks: list[dict[str, Any]]
    account_id: int
    backend_name: str

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None: ...

    def list_tickets_since(
        self,
        *,
        start_time: int | None = None,
        after_ts: int | None = None,
        after_id: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def sideload_for_tickets(
        self,
        tickets: list[dict[str, Any]],
        include: set[str],
    ) -> dict[str, list[dict[str, Any]]]: ...

    def update_ticket(
        self,
        ticket_id: int,
        patch: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None: ...

    def record_webhook(self, delivery: dict[str, Any]) -> None: ...
