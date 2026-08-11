"""
Ticket journey demo path (W1-PLT-06).

Simulates: ingest ticket → stub agents → console payload, with one shared
``run_id`` / ``trace_id`` across nested OpenTelemetry spans and JSON logs.
"""

from __future__ import annotations

import time
from typing import Any

from scout.observability.context import get_context
from scout.observability.logging import get_logger
from scout.observability.tracing import get_current_trace_id, start_span
from scout.service.db import Database
from scout.service.errors import AppError

logger = get_logger("scout.service.journey")

_TICKET_SQL = """
SELECT
    id,
    subject,
    status,
    priority,
    via_channel,
    organization_id,
    requester_id,
    assignee_id,
    created_at,
    updated_at
FROM src_zendesk.tickets
WHERE id = %s
"""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _run_ingest(db: Database, ticket_id: str) -> dict[str, Any]:
    with start_span(
        "ticket.ingest",
        attributes={"ticket.id": ticket_id, "miragent.stage": "ingest"},
    ):
        logger.info(
            "ticket.ingest.start",
            extra={"event": "ticket.ingest.start", "agent": "ingest"},
        )
        try:
            tid = int(ticket_id)
        except ValueError as exc:
            raise AppError(
                "invalid_ticket_id",
                f"ticket_id must be an integer, got {ticket_id!r}",
                status_code=400,
            ) from exc

        try:
            row = db.fetch_one(_TICKET_SQL, (tid,))
        except AppError as exc:
            if exc.code == "not_found":
                raise AppError(
                    "ticket_not_found",
                    f"Ticket {ticket_id} not found in src_zendesk.tickets",
                    status_code=404,
                ) from exc
            raise

        ticket = {
            "id": str(row["id"]),
            "subject": row["subject"],
            "status": row["status"],
            "priority": row["priority"],
            "via_channel": row["via_channel"],
            "organization_id": (
                str(row["organization_id"]) if row["organization_id"] is not None else None
            ),
            "requester_id": str(row["requester_id"]) if row["requester_id"] is not None else None,
            "assignee_id": str(row["assignee_id"]) if row["assignee_id"] is not None else None,
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        }
        logger.info(
            "ticket.ingest.ok",
            extra={"event": "ticket.ingest.ok", "agent": "ingest"},
        )
        return ticket


def _run_agent(name: str, ticket: dict[str, Any]) -> dict[str, Any]:
    with start_span(
        f"agent.{name}",
        attributes={
            "ticket.id": ticket["id"],
            "miragent.stage": "agent",
            "miragent.agent": name,
        },
    ):
        logger.info(
            f"agent.{name}.start",
            extra={"event": f"agent.{name}.start", "agent": name},
        )
        # Stub work — real agents land in later tickets; spans must still exist.
        time.sleep(0.005)
        result = {
            "name": name,
            "status": "ok",
            "summary": f"Stub {name} agent processed ticket {ticket['id']}",
        }
        logger.info(
            f"agent.{name}.ok",
            extra={"event": f"agent.{name}.ok", "agent": name},
        )
        return result


def _run_console(ticket: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    with start_span(
        "console.response",
        attributes={
            "ticket.id": ticket["id"],
            "miragent.stage": "console",
            "miragent.screen": "ticket-360",
        },
    ):
        logger.info(
            "console.response.start",
            extra={"event": "console.response.start", "agent": "console"},
        )
        payload = {
            "screen": "ticket-360",
            "visible": True,
            "agent_count": len(agents),
            "headline": ticket.get("subject") or f"Ticket {ticket['id']}",
        }
        logger.info(
            "console.response.ok",
            extra={"event": "console.response.ok", "agent": "console"},
        )
        return payload


def run_ticket_journey(db: Database, ticket_id: str) -> dict[str, Any]:
    """
    End-to-end demo path for observability.

    Returns a console-shaped payload that always includes ``run_id`` and
    ``trace_id`` so the same IDs are visible on-screen and in Jaeger.
    """
    ctx = get_context()
    run_id = ctx.run_id if ctx else None

    with start_span(
        "ticket.journey",
        attributes={"ticket.id": ticket_id, "miragent.stage": "journey"},
    ):
        ticket = _run_ingest(db, ticket_id)
        agents = [
            _run_agent("context", ticket),
            _run_agent("recommend", ticket),
        ]
        console = _run_console(ticket, agents)

        trace_id = get_current_trace_id()
        # Prefer context run_id; fall back should not happen under middleware
        if ctx is None or not run_id:
            from scout.observability.context import new_run_id

            run_id = new_run_id()

        body = {
            "run_id": run_id,
            "trace_id": trace_id,
            "ticket_id": ticket["id"],
            "ticket": ticket,
            "agents": agents,
            "console": console,
        }
        logger.info(
            "ticket.journey.complete",
            extra={"event": "ticket.journey.complete"},
        )
        return body
