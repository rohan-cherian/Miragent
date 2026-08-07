"""
Cursor-based incremental ticket export (Zendesk-faithful).

Endpoint shape: ``GET /api/v2/incremental/tickets/cursor``

  Initial:   ?start_time=<unix>
  Next page: ?cursor=<opaque>

Orders by ``generated_timestamp`` (then id). Terminates with
``end_of_stream: true`` when no further tickets remain in this export window.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote

from scout.emulators.zendesk.base import TicketStore


DEFAULT_PAGE_SIZE = 100
EXPORT_PATH = "/api/v2/incremental/tickets/cursor"


def encode_export_cursor(*, ts: int, ticket_id: int) -> str:
    """Opaque cursor pointing *after* (ts, ticket_id)."""
    payload = json.dumps(
        {"ts": int(ts), "id": int(ticket_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_export_cursor(cursor: str) -> tuple[int, int]:
    """Decode opaque export cursor → (generated_timestamp, ticket_id)."""
    if not cursor:
        raise ValueError("cursor must be non-empty")
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        data = json.loads(raw.decode())
        return int(data["ts"]), int(data["id"])
    except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid incremental cursor: {cursor!r}") from exc


def parse_include(raw: str | None) -> set[str]:
    """Parse Zendesk ``include=users,organizations`` sideload list."""
    if not raw or not str(raw).strip():
        return set()
    allowed = {"users", "organizations"}
    parts = {p.strip().lower() for p in str(raw).split(",") if p.strip()}
    return parts & allowed


def incremental_tickets_page(
    store: TicketStore,
    *,
    start_time: int | None = None,
    cursor: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    include: set[str] | None = None,
    force_partial: bool = False,
    base_path: str = EXPORT_PATH,
) -> dict[str, Any]:
    """
    Build one incremental export page.

    Exactly one of ``start_time`` (first page) or ``cursor`` (continuation)
    should be provided. If both are given, ``cursor`` wins (Zendesk behaviour
    once pagination has started).
    """
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    after_ts: int | None = None
    after_id: int | None = None
    filter_start: int | None = None

    if cursor:
        after_ts, after_id = decode_export_cursor(cursor)
    elif start_time is not None:
        filter_start = int(start_time)
    else:
        raise ValueError("start_time or cursor is required")

    take = page_size
    if force_partial and page_size > 1:
        take = max(1, page_size // 2)

    # Fetch one extra row so end_of_stream works without loading the full table.
    ordered = store.list_tickets_since(
        start_time=filter_start,
        after_ts=after_ts,
        after_id=after_id,
        limit=take + 1,
    )

    page = ordered[:take]
    end_of_stream = len(ordered) <= take

    body: dict[str, Any] = {
        "tickets": page,
        "end_of_stream": end_of_stream,
        "after_cursor": None,
        "after_url": None,
        "before_cursor": None,
        "before_url": None,
    }

    if page:
        last = page[-1]
        after_cursor = encode_export_cursor(
            ts=int(last["generated_timestamp"]),
            ticket_id=int(last["id"]),
        )
        body["after_cursor"] = after_cursor
        body["after_url"] = f"{base_path}?cursor={quote(after_cursor, safe='')}"

    include = include or set()
    if include and page:
        body.update(store.sideload_for_tickets(page, include))
    elif include:
        # Empty page still returns empty sideload arrays when requested.
        if "users" in include:
            body["users"] = []
        if "organizations" in include:
            body["organizations"] = []

    return body
