"""
Postgres-backed Zendesk store — reads/writes ``src_zendesk`` tables.

``generated_timestamp`` is derived from ``updated_at`` (fallback ``created_at``)
because the SQL schema dump does not include a dedicated generated_timestamp
column. Ordering matches real Zendesk incremental export semantics.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

# generated_timestamp expression shared by SELECT / WHERE / ORDER BY
_GEN_TS = (
    "FLOOR(EXTRACT(EPOCH FROM COALESCE(t.updated_at, t.created_at)))::bigint"
)

_TICKET_SELECT = f"""
SELECT
    t.id,
    t.external_id,
    t.requester_id,
    t.submitter_id,
    t.assignee_id,
    t.organization_id,
    t.group_id,
    t.subject,
    t.description,
    t.ticket_type AS type,
    t.priority,
    t.status,
    t.tags,
    t.custom_fields,
    t.via_channel,
    t.created_at,
    t.updated_at,
    {_GEN_TS} AS generated_timestamp
FROM src_zendesk.tickets t
"""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _ticket_from_row(row: dict[str, Any]) -> dict[str, Any]:
    tags = row.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    custom = row.get("custom_fields")
    if custom is not None and not isinstance(custom, (dict, list)):
        custom = None
    return {
        "id": int(row["id"]),
        "url": f"/api/v2/tickets/{int(row['id'])}.json",
        "external_id": row.get("external_id"),
        "subject": row.get("subject"),
        "description": row.get("description"),
        "status": row.get("status"),
        "priority": row.get("priority"),
        "type": row.get("type"),
        "requester_id": row.get("requester_id"),
        "submitter_id": row.get("submitter_id"),
        "assignee_id": row.get("assignee_id"),
        "organization_id": row.get("organization_id"),
        "group_id": row.get("group_id"),
        "tags": list(tags) if tags else [],
        "custom_fields": custom,
        "via": {"channel": row.get("via_channel")} if row.get("via_channel") else None,
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "generated_timestamp": int(row["generated_timestamp"]),
    }


def _user_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row.get("name"),
        "email": row.get("email"),
        "role": row.get("role"),
        "organization_id": row.get("organization_id"),
        "active": row.get("active"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _org_from_row(row: dict[str, Any]) -> dict[str, Any]:
    domains = row.get("domain_names") or []
    if isinstance(domains, str):
        domains = [domains]
    return {
        "id": int(row["id"]),
        "name": row.get("name"),
        "domain_names": list(domains) if domains else [],
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


# API field → SQL column for ticket updates
_UPDATE_COLUMNS = {
    "subject": "subject",
    "description": "description",
    "status": "status",
    "priority": "priority",
    "type": "ticket_type",
    "ticket_type": "ticket_type",
    "assignee_id": "assignee_id",
    "requester_id": "requester_id",
    "submitter_id": "submitter_id",
    "organization_id": "organization_id",
    "group_id": "group_id",
    "external_id": "external_id",
    "tags": "tags",
}


class PostgresZendeskStore:
    """
    Zendesk emulator store backed by PostgreSQL ``src_zendesk`` schema.

    Connection string example::

        postgresql://zendesk_admin:changeme_postgres@localhost:5432/zendesk_agent
    """

    backend_name = "postgres"

    def __init__(self, database_url: str) -> None:
        if not database_url or not str(database_url).strip():
            raise ValueError("database_url is required for PostgresZendeskStore")
        self.database_url = database_url.strip()
        self.webhook_secret = "dGhpc19zZWNyZXRfaXNfZm9yX3Rlc3Rpbmdfb25seQ=="
        self.webhook_url: str | None = None
        self.emitted_webhooks: list[dict[str, Any]] = []
        self.account_id = 1
        self._lock = threading.Lock()
        # Fail fast if DSN / schema is wrong
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'src_zendesk' AND table_name = 'tickets'"
                )
                if cur.fetchone() is None:
                    raise RuntimeError(
                        "Postgres schema src_zendesk.tickets not found. "
                        "Load schema/001_src_zendesk_schema.sql first "
                        "(see scripts/load_zendesk_postgres.py)."
                    )

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        sql = _TICKET_SELECT + " WHERE t.id = %s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ticket_id,))
                row = cur.fetchone()
        return _ticket_from_row(row) if row else None

    def list_tickets_since(
        self,
        *,
        start_time: int | None = None,
        after_ts: int | None = None,
        after_id: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if start_time is not None:
            clauses.append(f"{_GEN_TS} >= %s")
            params.append(int(start_time))

        if after_ts is not None and after_id is not None:
            clauses.append(f"({_GEN_TS}, t.id) > (%s, %s)")
            params.extend([int(after_ts), int(after_id)])

        sql = _TICKET_SELECT
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {_GEN_TS} ASC, t.id ASC"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(int(limit))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_ticket_from_row(r) for r in rows]

    def sideload_for_tickets(
        self,
        tickets: list[dict[str, Any]],
        include: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        extras: dict[str, list[dict[str, Any]]] = {}
        if not tickets or not include:
            if "users" in include:
                extras["users"] = []
            if "organizations" in include:
                extras["organizations"] = []
            return extras

        with self._connect() as conn:
            with conn.cursor() as cur:
                if "users" in include:
                    user_ids: set[int] = set()
                    for t in tickets:
                        for key in ("requester_id", "submitter_id", "assignee_id"):
                            uid = t.get(key)
                            if uid is not None:
                                user_ids.add(int(uid))
                    if user_ids:
                        cur.execute(
                            "SELECT id, name, email, role, organization_id, active, "
                            "created_at, updated_at "
                            "FROM src_zendesk.users WHERE id = ANY(%s) ORDER BY id",
                            (sorted(user_ids),),
                        )
                        extras["users"] = [_user_from_row(r) for r in cur.fetchall()]
                    else:
                        extras["users"] = []

                if "organizations" in include:
                    org_ids = {
                        int(t["organization_id"])
                        for t in tickets
                        if t.get("organization_id") is not None
                    }
                    if org_ids:
                        cur.execute(
                            "SELECT id, name, domain_names, created_at, updated_at "
                            "FROM src_zendesk.organizations WHERE id = ANY(%s) ORDER BY id",
                            (sorted(org_ids),),
                        )
                        extras["organizations"] = [
                            _org_from_row(r) for r in cur.fetchall()
                        ]
                    else:
                        extras["organizations"] = []
        return extras

    def update_ticket(
        self,
        ticket_id: int,
        patch: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        if self.get_ticket(ticket_id) is None:
            return None

        sets: list[str] = ["updated_at = NOW()"]
        params: list[Any] = []
        for key, value in patch.items():
            col = _UPDATE_COLUMNS.get(key)
            if col is None:
                continue
            if col == "tags" and value is not None and not isinstance(value, list):
                value = [value]
            if col == "custom_fields" and isinstance(value, (dict, list)):
                value = json.dumps(value)
            sets.append(f"{col} = %s")
            params.append(value)

        params.append(ticket_id)
        sql = f"UPDATE src_zendesk.tickets SET {', '.join(sets)} WHERE id = %s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        return self.get_ticket(ticket_id)

    def record_webhook(self, delivery: dict[str, Any]) -> None:
        with self._lock:
            self.emitted_webhooks.append(delivery)
