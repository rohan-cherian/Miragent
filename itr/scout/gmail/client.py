"""
Gmail API client (readonly) — list and fetch messages.

Uses one pooled ``httpx.Client`` for the process and retries 429 / 5xx with
exponential backoff. Gmail bills ``messages.get?format=full`` at 5 quota units
against a 250 unit/user/second budget, so a full-mailbox pull will hit the
limit; backing off is what keeps a large sync from dying halfway.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from scout.gmail.auth import (
    GmailStoredTokens,
    GmailTokenStore,
    refresh_access_token,
)
from scout.gmail.envelope import b64url_to_bytes

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 6


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
        timeout: float = 60.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._store = token_store
        self._user_id = user_id
        self._refresh_fallback = refresh_token_fallback
        self._tokens: GmailStoredTokens | None = None
        self._timeout = timeout
        self._http: httpx.Client | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    @property
    def http(self) -> httpx.Client:
        """Pooled connection — one TLS handshake instead of one per request."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.Client(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
            )
        return self._http

    def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            self._http.close()
        self._http = None

    def __enter__(self) -> GmailClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── auth ──────────────────────────────────────────────────────────────────

    def _ensure_tokens(self) -> GmailStoredTokens:
        now = time.time()
        if self._tokens and self._tokens.expires_at > now + 60:
            return self._tokens

        stored = self._store.load()
        refresh = (stored.refresh_token if stored else "") or self._refresh_fallback
        if not refresh:
            raise RuntimeError(
                "No Gmail refresh token. Run: poetry run python scripts/gmail_oauth_login.py"
            )

        if stored and stored.access_token and stored.expires_at > now + 60:
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

    # ── transport ─────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{GMAIL_API}{path}"
        last_exc: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                res = self.http.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_body,
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                self._sleep_backoff(attempt, None, reason=type(exc).__name__)
                continue

            if res.status_code == 401 and attempt < MAX_ATTEMPTS - 1:
                # Access token rejected mid-run — force a refresh and retry once.
                logger.info("Gmail returned 401; refreshing token")
                self._tokens = None
                continue

            if res.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS - 1:
                self._sleep_backoff(
                    attempt,
                    res.headers.get("Retry-After"),
                    reason=f"HTTP {res.status_code}",
                )
                continue

            res.raise_for_status()
            return res.json() if res.content else {}

        if last_exc is not None:  # pragma: no cover - defensive
            raise last_exc
        raise RuntimeError(f"Gmail request failed after {MAX_ATTEMPTS} attempts: {path}")

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: str | None, *, reason: str) -> None:
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 2.0 ** attempt
        else:
            delay = 2.0 ** attempt
        delay = min(delay, 60.0) + random.uniform(0, 0.5)  # jitter avoids lockstep retries
        logger.warning("Gmail %s — backing off %.1fs (attempt %d)", reason, delay, attempt + 1)
        time.sleep(delay)

    # ── reads ─────────────────────────────────────────────────────────────────

    def get_profile(self) -> dict[str, Any]:
        return self._get(f"/users/{self._user_id}/profile")

    def list_message_refs(
        self,
        *,
        max_results: int = 10,
        page_token: str | None = None,
        q: str | None = None,
        include_spam_trash: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        if q:
            params["q"] = q
        if include_spam_trash:
            params["includeSpamTrash"] = "true"
        return self._get(f"/users/{self._user_id}/messages", params)

    def iter_all_message_ids(
        self,
        *,
        q: str | None = None,
        include_spam_trash: bool = True,
        page_size: int = 100,
        limit: int | None = None,
        start_page_token: str | None = None,
    ) -> Iterator[tuple[str, str | None]]:
        """
        Every message id in the mailbox, newest first.

        Yields ``(message_id, next_page_token)`` so a caller can persist the
        token and resume a backfill that was interrupted.
        """
        page_token = start_page_token
        seen = 0
        while True:
            data = self.list_message_refs(
                max_results=min(page_size, 500),
                page_token=page_token,
                q=q or None,
                include_spam_trash=include_spam_trash,
            )
            next_token = data.get("nextPageToken")
            for ref in data.get("messages") or []:
                mid = ref.get("id")
                if not mid:
                    continue
                yield mid, next_token
                seen += 1
                if limit is not None and seen >= limit:
                    return
            page_token = next_token
            if not page_token:
                return

    def get_message(self, message_id: str, *, format: str = "full") -> dict[str, Any]:
        return self._get(
            f"/users/{self._user_id}/messages/{message_id}",
            {"format": format},
        )

    def get_attachment_bytes(self, *, message_id: str, attachment_id: str) -> bytes:
        """Attachment payload. Gmail returns base64url in a ``data`` field."""
        data = self._get(
            f"/users/{self._user_id}/messages/{message_id}/attachments/{attachment_id}"
        )
        return b64url_to_bytes(data.get("data") or "")

    def list_history_message_ids(
        self,
        *,
        start_history_id: str,
        history_types: str = "messageAdded",
    ) -> tuple[list[str], str | None]:
        """
        Return new/changed message ids since ``start_history_id``.

        Raises ``httpx.HTTPStatusError`` with 404 when the history id is too old
        (caller should fall back to a full list sync).
        """
        ids: list[str] = []
        page_token: str | None = None
        newest_history: str | None = None
        while True:
            params: dict[str, Any] = {
                "startHistoryId": start_history_id,
                "historyTypes": history_types,
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get(f"/users/{self._user_id}/history", params)
            if data.get("historyId") is not None:
                newest_history = str(data["historyId"])
            for entry in data.get("history") or []:
                for added in entry.get("messagesAdded") or []:
                    mid = (added.get("message") or {}).get("id")
                    if mid:
                        ids.append(mid)
                # messagesAdded misses nothing for ingestion, but label changes
                # can surface a message we have never seen (e.g. un-trashed).
                for key in ("labelsAdded", "labelsRemoved"):
                    for change in entry.get(key) or []:
                        mid = (change.get("message") or {}).get("id")
                        if mid:
                            ids.append(mid)
            page_token = data.get("nextPageToken")
            if not page_token:
                break

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

    # ── push (Cloud Pub/Sub) ──────────────────────────────────────────────────

    def watch(
        self,
        *,
        topic_name: str,
        label_ids: list[str] | None = None,
        label_filter_behavior: str = "include",
    ) -> dict[str, Any]:
        """
        Register push notifications to a Pub/Sub topic.

        Returns ``{"historyId": ..., "expiration": <ms>}``. Gmail expires a
        watch after 7 days, so this must be re-called well before then.
        """
        body: dict[str, Any] = {"topicName": topic_name}
        if label_ids:
            body["labelIds"] = label_ids
            body["labelFilterBehavior"] = label_filter_behavior
        return self._request("POST", f"/users/{self._user_id}/watch", json_body=body)

    def stop_watch(self) -> None:
        self._request("POST", f"/users/{self._user_id}/stop")


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
    return b64url_to_bytes(data).decode("utf-8", errors="replace")


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


def get_client(*, use_fixtures: bool | None = None, **kwargs):
    """Return the Gmail client this environment should use.

    Task 9: when ``USE_GMAIL_FIXTURES`` is true, hand back a FixtureClient
    reading exported JSON instead of calling Gmail. Nothing upstream changes —
    the sync, the scripts and the tests all keep calling the same methods, so a
    dead token or dropped wifi stops being a demo-ending problem.

    The import is local so that fixture code is not pulled in on the live path.
    """
    from scout.config import settings

    if use_fixtures is None:
        use_fixtures = settings.use_gmail_fixtures

    if use_fixtures:
        from scout.gmail.fixtures import FixtureClient

        logger.info("Gmail: using offline fixtures (%s)", settings.gmail_fixtures_dir)
        return FixtureClient(**kwargs)

    # Live path defaults itself from settings, so get_client() takes no
    # arguments on either branch — a factory the caller has to configure
    # differently per branch is not much of a factory.
    if not kwargs:
        from scout.gmail.auth import GmailTokenStore

        kwargs = {
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "token_store": GmailTokenStore(settings.gmail_token_path),
            "user_id": "me",
            "refresh_token_fallback": settings.gmail_refresh_token,
        }
    return GmailClient(**kwargs)
