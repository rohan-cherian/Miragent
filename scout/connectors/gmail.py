"""
Production Gmail connector (Phase 4).

Reads mail via Desktop OAuth refresh token (secrets/gmail_token.json).
Entity type: ``email_message``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone

from scout.connectors.base import ConnectorBase
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ConnectorHealth,
    EntitySchema,
    ExtractionCursor,
    RawRecord,
)
from scout.gmail.auth import GmailTokenStore
from scout.gmail.client import GmailClient, GmailMessage

logger = logging.getLogger(__name__)


class GmailConnector(ConnectorBase):
    """
    Gmail readonly connector.

    Credentials (auth_data keys):
        client_id / client_secret — OAuth Desktop client
        refresh_token             — optional fallback
        token_path                — default secrets/gmail_token.json
        user_id                   — default ``me``
    """

    CONNECTOR_ID = "gmail"
    DISPLAY_NAME = "Gmail (Readonly)"
    CATEGORY = ConnectorCategory.PRODUCTIVITY
    CALLS_PER_SECOND = 5.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._client: GmailClient | None = None

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        client_id = auth.get("client_id") or ""
        client_secret = auth.get("client_secret") or ""
        if not client_id or not client_secret:
            logger.error("GmailConnector: missing client_id / client_secret")
            return False
        try:
            self._client = GmailClient(
                client_id=client_id,
                client_secret=client_secret,
                token_store=GmailTokenStore(
                    auth.get("token_path") or "secrets/gmail_token.json"
                ),
                user_id=auth.get("user_id") or "me",
                refresh_token_fallback=auth.get("refresh_token") or "",
            )
            self._client.get_profile()
            return True
        except Exception:
            logger.exception("GmailConnector: authenticate failed")
            self._client = None
            return False

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="email_message",
                display_name="Gmail Message",
                supports_incremental=True,
                fields=[
                    "id",
                    "thread_id",
                    "subject",
                    "from",
                    "to",
                    "snippet",
                    "body_text",
                    "internal_date_ms",
                ],
            )
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type != "email_message":
            return
        if self._client is None and not self.authenticate():
            return
        assert self._client is not None
        for msg in self._client.fetch_messages(max_results=100, q="in:inbox"):
            yield self._to_raw(msg)

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        if entity_type != "email_message":
            return iter(()), cursor
        if self._client is None and not self.authenticate():
            return iter(()), cursor
        assert self._client is not None

        last_ms = int(cursor.checkpoint.get("last_internal_date_ms") or 0)

        messages = self._client.fetch_messages(max_results=100, q="in:inbox")
        newer = [
            m
            for m in messages
            if m.internal_date_ms is not None and m.internal_date_ms > last_ms
        ]
        max_ms = max((m.internal_date_ms or 0 for m in newer), default=last_ms)
        new_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(timezone.utc),
            checkpoint={"last_internal_date_ms": max_ms},
        )

        def _gen() -> Iterator[RawRecord]:
            for msg in newer:
                yield self._to_raw(msg)

        return _gen(), new_cursor

    def health_check(self) -> ConnectorHealth:
        started = time.time()
        if self._client is None and not self.authenticate():
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                error_message="not authenticated",
            )
        try:
            assert self._client is not None
            self._client.get_profile()
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=(time.time() - started) * 1000.0,
            )
        except Exception as exc:
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                error_message=str(exc),
                latency_ms=(time.time() - started) * 1000.0,
            )

    def _to_raw(self, msg: GmailMessage) -> RawRecord:
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type="email_message",
            source_id=msg.id,
            tenant_id=self.tenant_id,
            payload={
                "id": msg.id,
                "thread_id": msg.thread_id,
                "subject": msg.subject,
                "from": msg.from_header,
                "to": msg.to_header,
                "snippet": msg.snippet,
                "body_text": msg.body_text,
                "internal_date_ms": msg.internal_date_ms,
                "history_id": msg.history_id,
                "label_ids": list(msg.label_ids),
            },
            email_hint=_email_from_header(msg.from_header),
            name_hint=msg.subject,
        )


def _email_from_header(header: str) -> str | None:
    if not header:
        return None
    if "<" in header and ">" in header:
        return header.split("<", 1)[1].split(">", 1)[0].strip()
    if "@" in header:
        return header.strip()
    return None
