"""
scout/connectors/zendesk.py — Production Zendesk Connector (Sprint 35)

Zendesk is the dominant customer support platform for PE-backed B2B SaaS
companies ($10M–$300M ARR). For Miragent, Zendesk surfaces:
  - Customer health signals: ticket volume, CSAT, escalation rates
  - Offboarding completeness: departed agents still with open tickets assigned
  - Key account risk: enterprise accounts with spike in support volume
  - Churn risk: accounts with recurring P0 support tickets

Authentication:
  Zendesk supports:
    - Basic Auth: email + password (legacy, not recommended)
    - API Token: email/token + api_token (recommended for integrations)
    - OAuth 2.0: access token (for user-delegated flows)

  API token auth:
    Header: Authorization: Basic base64("{email}/token:{api_token}")

API structure:
  Base: https://{subdomain}.zendesk.com
  - /api/v2/tickets         → support tickets
  - /api/v2/users           → agents and end-users
  - /api/v2/organizations   → customer organizations
  - /api/v2/ticket_metrics  → per-ticket performance metrics

Pagination:
  Zendesk uses cursor-based pagination for most endpoints.
  Response: { "tickets": [...], "meta": { "has_more": true, "after_cursor": "..." } }
  Legacy: { "tickets": [...], "next_page": "https://..." }

Rate limits:
  Zendesk: 700 requests/minute (Enterprise), 200/min (others).
  We use 8/sec (480/min) as a safe default.

Entity types:
  - ticket       → support tickets
  - user         → Zendesk agents and end-users
  - organization → customer organization records
"""

import base64
import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import httpx

from scout.connectors.base import ConnectorBase
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ConnectorHealth,
    EntitySchema,
    ExtractionCursor,
    RawRecord,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100  # Zendesk default max per page


class ZendeskConnector(ConnectorBase):
    """
    Production Zendesk Support connector.

    Supports API token auth (recommended) and OAuth Bearer tokens.

    Credentials (auth_data keys — API Token):
        auth_mode   — "api_token" (default) or "oauth"
        subdomain   — Zendesk subdomain, e.g. "acme" (→ acme.zendesk.com)
        email       — Agent email address
        api_token   — Zendesk API token

    Credentials (auth_data keys — OAuth):
        auth_mode    — "oauth"
        subdomain    — Zendesk subdomain
        access_token — OAuth access token
    """

    CONNECTOR_ID = "zendesk"
    DISPLAY_NAME = "Zendesk Support (Production)"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 8.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._auth_header: str = ""
        self._base_url: str = ""
        self._auth_mode: str = "api_token"

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        self._auth_mode = auth.get("auth_mode", "api_token")
        subdomain = auth.get("subdomain", "")

        if not subdomain:
            logger.error("ZendeskConnector: missing required auth_data key 'subdomain'")
            return False

        self._base_url = f"https://{subdomain}.zendesk.com"

        if self._auth_mode == "api_token":
            return self._authenticate_api_token(auth)
        elif self._auth_mode == "oauth":
            return self._authenticate_oauth(auth)
        else:
            logger.error(
                "ZendeskConnector: unknown auth_mode '%s'. Use 'api_token' or 'oauth'.",
                self._auth_mode,
            )
            return False

    def _authenticate_api_token(self, auth: dict) -> bool:
        email = auth.get("email", "")
        api_token = auth.get("api_token", "")
        if not email or not api_token:
            logger.error("ZendeskConnector API token: missing 'email' or 'api_token'")
            return False

        # Zendesk API token format: {email}/token:{api_token}
        raw = f"{email}/token:{api_token}"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()
        return self._validate_connection()

    def _authenticate_oauth(self, auth: dict) -> bool:
        access_token = auth.get("access_token", "")
        if not access_token:
            logger.error("ZendeskConnector OAuth: missing 'access_token'")
            return False
        self._auth_header = f"Bearer {access_token}"
        return self._validate_connection()

    def _validate_connection(self) -> bool:
        try:
            resp = self._http_client.get(
                f"{self._base_url}/api/v2/users/me",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            user = data.get("user", {})
            logger.info(
                "ZendeskConnector authenticated: user=%s tenant=%s",
                user.get("email", "?"), self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("ZendeskConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("ZendeskConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="ticket",
                display_name="Zendesk Tickets",
                supports_incremental=True,
                fields=[
                    "id", "subject", "description", "status", "priority", "type",
                    "requester_id", "submitter_id", "assignee_id", "organization_id",
                    "group_id", "tags", "satisfaction_rating",
                    "created_at", "updated_at", "solved_at",
                    "due_at", "via",
                ],
            ),
            EntitySchema(
                entity_type="user",
                display_name="Zendesk Users",
                supports_incremental=True,
                fields=[
                    "id", "name", "email", "role", "active",
                    "organization_id", "phone", "time_zone",
                    "locale", "tags", "verified",
                    "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="organization",
                display_name="Zendesk Organizations",
                supports_incremental=True,
                fields=[
                    "id", "name", "domain_names", "details",
                    "notes", "group_id", "tags",
                    "created_at", "updated_at",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        config = self._entity_config(entity_type)
        yield from self._paginate_zendesk(
            endpoint=config["endpoint"],
            records_key=config["key"],
            entity_type=entity_type,
        )

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Incremental via Zendesk's incremental export API.
        GET /api/v2/incremental/{entity}.json?start_time={unix_timestamp}

        Returns records modified since start_time (Unix epoch seconds).
        """
        config = self._entity_config(entity_type)
        start_ts = int(cursor.last_extracted_at.timestamp())
        incremental_endpoint = config.get("incremental_endpoint", config["endpoint"])
        incremental_key = config.get("incremental_key", config["key"])

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_incremental(
                endpoint=incremental_endpoint,
                records_key=incremental_key,
                entity_type=entity_type,
                start_time=start_ts,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"start_time": start_ts},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{self._base_url}/api/v2/users/me",
                headers=self._headers(),
            )
            _ = resp.get("user", {})
            latency_ms = (time.monotonic() - start) * 1000
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    # ─────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _entity_config(self, entity_type: str) -> dict[str, str]:
        configs = {
            "ticket": {
                "endpoint": "/api/v2/tickets",
                "key": "tickets",
                "incremental_endpoint": "/api/v2/incremental/tickets.json",
                "incremental_key": "tickets",
            },
            "user": {
                "endpoint": "/api/v2/users",
                "key": "users",
                "incremental_endpoint": "/api/v2/incremental/users.json",
                "incremental_key": "users",
            },
            "organization": {
                "endpoint": "/api/v2/organizations",
                "key": "organizations",
                "incremental_endpoint": "/api/v2/incremental/organizations.json",
                "incremental_key": "organizations",
            },
        }
        if entity_type not in configs:
            raise ValueError(
                f"ZendeskConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_zendesk(
        self,
        endpoint: str,
        records_key: str,
        entity_type: str,
    ) -> Iterator[RawRecord]:
        """
        Paginate Zendesk using cursor-based pagination.
        Supports both meta.after_cursor (new) and next_page (legacy) styles.
        """
        url: str | None = f"{self._base_url}{endpoint}"
        params: dict[str, Any] = {"per_page": _PAGE_SIZE}

        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error(
                    "ZendeskConnector pagination error (endpoint=%s): %s", endpoint, exc
                )
                break

            records = resp.get(records_key, [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            # Cursor-based pagination (new style)
            meta = resp.get("meta", {})
            if meta.get("has_more") and meta.get("after_cursor"):
                params = {"page[after]": meta["after_cursor"], "per_page": _PAGE_SIZE}
                url = f"{self._base_url}{endpoint}"
            else:
                # Legacy next_page URL
                url = resp.get("next_page")
                params = {}

    def _paginate_incremental(
        self,
        endpoint: str,
        records_key: str,
        entity_type: str,
        start_time: int,
    ) -> Iterator[RawRecord]:
        """
        Paginate Zendesk incremental export API.
        Response: { "tickets": [...], "end_time": N, "count": N, "end_of_stream": true/false }
        """
        url: str | None = f"{self._base_url}{endpoint}"
        params: dict[str, Any] = {"start_time": start_time}

        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error("ZendeskConnector incremental error (endpoint=%s): %s", endpoint, exc)
                break

            records = resp.get(records_key, [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            if resp.get("end_of_stream", True):
                break

            # Next page uses end_time as new start_time
            end_time = resp.get("end_time")
            if end_time:
                params = {"start_time": end_time}
            else:
                break

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        email = record.get("email") or record.get("requester_email")
        name = (
            record.get("name")
            or record.get("subject")
            or None
        )
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.tenant_id,
            payload=record,
            email_hint=email or None,
            name_hint=name or None,
        )
