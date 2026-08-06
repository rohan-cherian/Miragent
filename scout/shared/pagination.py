"""
Shared pagination for vendor API emulators.

Three real styles — vendors genuinely differ:

  Zendesk — cursor-based with opaque ``after_cursor`` / ``page[after]``
  Jira    — offset with ``startAt`` / ``maxResults`` / ``total``
  Entra   — OData ``$skiptoken`` / ``@odata.nextLink``

Emulators slice an in-memory collection and return the vendor-shaped page
envelope so connectors exercise the same pagination paths they use in prod.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse, urlunparse


# ── Opaque Zendesk cursor ────────────────────────────────────────────────────


def encode_zendesk_cursor(offset: int) -> str:
    """Encode a list offset as an opaque Zendesk-style after_cursor."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    payload = json.dumps({"o": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_zendesk_cursor(cursor: str) -> int:
    """Decode an opaque after_cursor back to a list offset."""
    if not cursor:
        raise ValueError("cursor must be non-empty")
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        data = json.loads(raw.decode())
        offset = int(data["o"])
    except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid Zendesk cursor: {cursor!r}") from exc
    if offset < 0:
        raise ValueError("cursor offset must be >= 0")
    return offset


def encode_odata_skiptoken(offset: int) -> str:
    """Encode an offset as an opaque OData $skiptoken."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    payload = json.dumps({"skip": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_odata_skiptoken(token: str) -> int:
    """Decode an OData $skiptoken back to a list offset."""
    if not token:
        raise ValueError("skiptoken must be non-empty")
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token + padding)
        data = json.loads(raw.decode())
        offset = int(data["skip"])
    except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid OData skiptoken: {token!r}") from exc
    if offset < 0:
        raise ValueError("skiptoken offset must be >= 0")
    return offset


# ── Page result ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageSlice:
    """Raw slice of items plus pagination bookkeeping."""

    items: list[Any]
    offset: int
    page_size: int
    total: int
    has_more: bool
    next_offset: int | None

    @property
    def is_partial(self) -> bool:
        """True when this page has fewer items than ``page_size`` but more remain.

        Used by chaos mode to return truncated pages without closing the stream.
        """
        return self.has_more and len(self.items) < self.page_size


def slice_items(
    items: Sequence[Any],
    *,
    offset: int,
    page_size: int,
    force_partial: bool = False,
) -> PageSlice:
    """
    Slice ``items`` starting at ``offset``.

    If ``force_partial`` is True and enough items remain, return only half a
    page (still with ``has_more=True``) — used by chaos injection.
    """
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    total = len(items)
    if offset >= total:
        return PageSlice(
            items=[],
            offset=offset,
            page_size=page_size,
            total=total,
            has_more=False,
            next_offset=None,
        )

    take = page_size
    if force_partial and page_size > 1:
        take = max(1, page_size // 2)

    end = min(offset + take, total)
    page = list(items[offset:end])
    next_offset = end if end < total else None
    return PageSlice(
        items=page,
        offset=offset,
        page_size=page_size,
        total=total,
        has_more=next_offset is not None,
        next_offset=next_offset,
    )


# ── Zendesk cursor pagination ────────────────────────────────────────────────


def paginate_zendesk(
    items: Sequence[Any],
    *,
    after_cursor: str | None = None,
    per_page: int = 100,
    resource_key: str = "tickets",
    path: str = "/api/v2/tickets",
    force_partial: bool = False,
) -> dict[str, Any]:
    """
    Build a Zendesk cursor-paginated response.

    Request style: ``?page[after]=<cursor>&per_page=N``
    Response style::

        {
          "<resource_key>": [...],
          "meta": {"has_more": true, "after_cursor": "<opaque>"},
          "links": {"next": "...?page[after]=..."}
        }
    """
    offset = decode_zendesk_cursor(after_cursor) if after_cursor else 0
    page = slice_items(
        items, offset=offset, page_size=per_page, force_partial=force_partial
    )

    meta: dict[str, Any] = {"has_more": page.has_more}
    links: dict[str, Any] = {"next": None}

    if page.has_more and page.next_offset is not None:
        cursor = encode_zendesk_cursor(page.next_offset)
        meta["after_cursor"] = cursor
        links["next"] = f"{path}?page[after]={cursor}&per_page={per_page}"

    return {
        resource_key: page.items,
        "meta": meta,
        "links": links,
    }


# ── Jira startAt / maxResults ────────────────────────────────────────────────


def paginate_jira(
    items: Sequence[Any],
    *,
    start_at: int = 0,
    max_results: int = 50,
    resource_key: str = "issues",
    force_partial: bool = False,
) -> dict[str, Any]:
    """
    Build a Jira offset-paginated response.

    Request style: ``?startAt=0&maxResults=50``
    Response style::

        {
          "startAt": 0,
          "maxResults": 50,
          "total": N,
          "issues": [...]
        }
    """
    if start_at < 0:
        raise ValueError("startAt must be >= 0")
    if max_results < 1:
        raise ValueError("maxResults must be >= 1")

    page = slice_items(
        items, offset=start_at, page_size=max_results, force_partial=force_partial
    )
    return {
        "startAt": start_at,
        "maxResults": max_results,
        "total": page.total,
        resource_key: page.items,
    }


# ── Entra / Microsoft Graph OData ────────────────────────────────────────────


def paginate_entra(
    items: Sequence[Any],
    *,
    skiptoken: str | None = None,
    top: int = 100,
    base_url: str = "https://graph.microsoft.com/v1.0/users",
    force_partial: bool = False,
) -> dict[str, Any]:
    """
    Build a Microsoft Graph / Entra OData page.

    Request style: ``?$top=100`` then follow ``@odata.nextLink`` which embeds
    ``$skiptoken``.
    Response style::

        {
          "@odata.context": ".../$metadata#users",
          "value": [...],
          "@odata.nextLink": "https://...?$skiptoken=..."
        }
    """
    if top < 1:
        raise ValueError("$top must be >= 1")

    offset = decode_odata_skiptoken(skiptoken) if skiptoken else 0
    page = slice_items(items, offset=offset, page_size=top, force_partial=force_partial)

    body: dict[str, Any] = {
        "@odata.context": f"{_graph_context(base_url)}",
        "value": page.items,
    }

    if page.has_more and page.next_offset is not None:
        token = encode_odata_skiptoken(page.next_offset)
        body["@odata.nextLink"] = _build_next_link(base_url, top=top, skiptoken=token)

    return body


def _graph_context(base_url: str) -> str:
    parsed = urlparse(base_url)
    # e.g. https://graph.microsoft.com/v1.0/users → .../$metadata#users
    resource = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "collection"
    root = f"{parsed.scheme}://{parsed.netloc}"
    # Keep version prefix if present (/v1.0/...)
    parts = [p for p in parsed.path.split("/") if p]
    version = parts[0] if parts and parts[0].startswith("v") else "v1.0"
    return f"{root}/{version}/$metadata#{resource}"


def _build_next_link(base_url: str, *, top: int, skiptoken: str) -> str:
    """
    Build a Graph-style nextLink.

    Real Microsoft Graph links keep the literal ``$`` in ``$top`` / ``$skiptoken``
    (they are not percent-encoded as ``%24``).
    """
    parsed = urlparse(base_url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    # Drop prior paging params; preserve any other query args on base_url.
    for key in ("$top", "$skiptoken", "top", "skiptoken"):
        existing.pop(key, None)

    parts: list[str] = []
    for key, values in existing.items():
        for value in values:
            parts.append(f"{key}={value}")
    parts.append(f"$top={top}")
    parts.append(f"$skiptoken={skiptoken}")
    return urlunparse(parsed._replace(query="&".join(parts)))


def parse_entra_skiptoken_from_url(next_link: str) -> str | None:
    """Extract ``$skiptoken`` from an ``@odata.nextLink`` URL."""
    query = parse_qs(urlparse(next_link).query)
    values = query.get("$skiptoken") or query.get("skiptoken")
    return values[0] if values else None
