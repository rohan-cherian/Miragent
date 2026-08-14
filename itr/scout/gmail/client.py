"""
Gmail API client (readonly) — list and fetch messages.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from scout.gmail.auth import (
    GmailStoredTokens,
    GmailTokenStore,
    refresh_access_token,
)

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    history_id: str | None
    internal_date_ms: int | None
    subject: str
    from_header: str
    to_header: str
    snippet: str
    body_text: str
    label_ids: tuple[str, ...]


class GmailClient:
    """Thin REST client over Gmail API v1."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        token_store: GmailTokenStore,
        user_id: str = "me",
        refresh_token_fallback: str = "",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._store = token_store
        self._user_id = user_id
        self._refresh_fallback = refresh_token_fallback
        self._tokens: GmailStoredTokens | None = None

    def _ensure_tokens(self) -> GmailStoredTokens:
        if self._tokens and self._tokens.expires_at > __import__("time").time() + 60:
            return self._tokens

        stored = self._store.load()
        refresh = (stored.refresh_token if stored else "") or self._refresh_fallback
        if not refresh:
            raise RuntimeError(
                "No Gmail refresh token. Run: poetry run python scripts/gmail_oauth_login.py"
            )

        # Reuse access token if still valid
        if stored and stored.access_token and stored.expires_at > __import__("time").time() + 60:
            self._tokens = stored
            return stored

        logger.info("Refreshing Gmail access token")
        fresh = refresh_access_token(
            refresh_token=refresh,
            client_id=self._client_id,
            client_secret=self._client_secret,
        )
        self._store.save(fresh)
        self._tokens = fresh
        return fresh

    def _headers(self) -> dict[str, str]:
        tokens = self._ensure_tokens()
        return {"Authorization": f"Bearer {tokens.access_token}"}

    def get_profile(self) -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                f"{GMAIL_API}/users/{self._user_id}/profile",
                headers=self._headers(),
            )
            res.raise_for_status()
            return res.json()

    def list_message_refs(
        self,
        *,
        max_results: int = 10,
        page_token: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        if q:
            params["q"] = q
        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                f"{GMAIL_API}/users/{self._user_id}/messages",
                headers=self._headers(),
                params=params,
            )
            res.raise_for_status()
            return res.json()

    def get_message(self, message_id: str, *, format: str = "full") -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                f"{GMAIL_API}/users/{self._user_id}/messages/{message_id}",
                headers=self._headers(),
                params={"format": format},
            )
            res.raise_for_status()
            return res.json()

    def list_history_message_ids(self, *, start_history_id: str) -> tuple[list[str], str | None]:
        """
        Return new/changed message ids since ``start_history_id``.

        Raises ``httpx.HTTPStatusError`` with 404 when the history id is too old
        (caller should fall back to a full list sync).
        """
        ids: list[str] = []
        page_token: str | None = None
        newest_history: str | None = None
        with httpx.Client(timeout=60.0) as client:
            while True:
                params: dict[str, Any] = {
                    "startHistoryId": start_history_id,
                    "historyTypes": "messageAdded",
                }
                if page_token:
                    params["pageToken"] = page_token
                res = client.get(
                    f"{GMAIL_API}/users/{self._user_id}/history",
                    headers=self._headers(),
                    params=params,
                )
                res.raise_for_status()
                data = res.json()
                if data.get("historyId") is not None:
                    newest_history = str(data["historyId"])
                for entry in data.get("history") or []:
                    for added in entry.get("messagesAdded") or []:
                        mid = (added.get("message") or {}).get("id")
                        if mid:
                            ids.append(mid)
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        # Preserve order, drop dupes
        seen: set[str] = set()
        unique: list[str] = []
        for mid in ids:
            if mid not in seen:
                seen.add(mid)
                unique.append(mid)
        return unique, newest_history

    def fetch_messages(self, *, max_results: int = 10, q: str | None = None) -> list[GmailMessage]:
        listing = self.list_message_refs(max_results=max_results, q=q)
        out: list[GmailMessage] = []
        for ref in listing.get("messages") or []:
            raw = self.get_message(ref["id"], format="full")
            out.append(parse_message(raw))
        return out

    def fetch_messages_by_ids(self, message_ids: list[str]) -> list[GmailMessage]:
        out: list[GmailMessage] = []
        for mid in message_ids:
            raw = self.get_message(mid, format="full")
            out.append(parse_message(raw))
        return out


def parse_message(raw: dict[str, Any]) -> GmailMessage:
    headers = {
        h["name"].lower(): h["value"]
        for h in (raw.get("payload") or {}).get("headers") or []
        if "name" in h and "value" in h
    }
    body = _extract_body_text(raw.get("payload") or {})
    internal = raw.get("internalDate")
    return GmailMessage(
        id=raw["id"],
        thread_id=raw.get("threadId") or "",
        history_id=str(raw["historyId"]) if raw.get("historyId") is not None else None,
        internal_date_ms=int(internal) if internal is not None else None,
        subject=headers.get("subject") or "(no subject)",
        from_header=headers.get("from") or "",
        to_header=headers.get("to") or "",
        snippet=raw.get("snippet") or "",
        body_text=body,
        label_ids=tuple(raw.get("labelIds") or ()),
    )


def _extract_body_text(payload: dict[str, Any]) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    mime = payload.get("mimeType") or ""
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime.startswith("text/plain"):
        return _b64url_decode(data)
    if data and mime.startswith("text/html"):
        return _strip_html(_b64url_decode(data))

    texts: list[str] = []
    htmls: list[str] = []
    for part in payload.get("parts") or []:
        part_mime = part.get("mimeType") or ""
        part_data = (part.get("body") or {}).get("data")
        if part.get("parts"):
            nested = _extract_body_text(part)
            if nested:
                texts.append(nested)
            continue
        if not part_data:
            continue
        decoded = _b64url_decode(part_data)
        if part_mime.startswith("text/plain"):
            texts.append(decoded)
        elif part_mime.startswith("text/html"):
            htmls.append(_strip_html(decoded))

    if texts:
        return "\n".join(texts).strip()
    if htmls:
        return "\n".join(htmls).strip()
    return ""


def _b64url_decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_internal_date(ms: int | None) -> str:
    if ms is None:
        return ""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return str(ms)
