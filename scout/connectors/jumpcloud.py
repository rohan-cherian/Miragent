"""
scout/connectors/jumpcloud.py — Production JumpCloud Connector (Sprint 37)

JumpCloud is a cloud directory platform (Directory-as-a-Service) that manages
user identities, device management, and SSO for SMB and mid-market companies.
Often used as a lightweight alternative to Active Directory or Okta.

For Miragent:
  - User directory: all employees and their access status
  - System associations: which devices is a user bound to?
  - App SSO assignments: which SSO apps does each user have?
  - Offboarding: verify user is suspended/deleted in JumpCloud

Authentication:
  JumpCloud uses an API key passed in the `x-api-key` header.

API structure:
  Base: https://console.jumpcloud.com/api
  - /v2/users              → system users (v2)
  - /v1/systemusers        → system users (v1, more fields)
  - /v2/applications       → SSO applications
  - /v2/groups/user        → user groups
  - /v2/systemusers/{id}/associations → user→application mapping

Pagination:
  JumpCloud uses limit + skip with a totalCount in some responses.
  Response: [ ...records... ] (array directly, no wrapper)

Rate limits:
  JumpCloud: 120 requests/minute.
  We use 1.5/sec (90/min) as a safe default.

Entity types:
  - user         → JumpCloud system users
  - group        → JumpCloud user groups
  - application  → SSO application configurations
"""

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

_API_BASE = "https://console.jumpcloud.com"
_PAGE_SIZE = 100  # JumpCloud max per request


class JumpCloudConnector(ConnectorBase):
    """
    Production JumpCloud Directory connector.

    Credentials (auth_data keys):
        api_key  — JumpCloud admin API key (x-api-key header)
    """

    CONNECTOR_ID = "jumpcloud"
    DISPLAY_NAME = "JumpCloud Directory (Production)"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 1.5

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_key: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        api_key = auth.get("api_key", "")

        if not api_key:
            logger.error("JumpCloudConnector: missing required auth_data key 'api_key'")
            return False

        self._api_key = api_key

        # Validate by fetching 1 user
        try:
            resp = self._http_client.get(
                f"{_API_BASE}/api/v1/systemusers",
                params={"limit": 1, "skip": 0},
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info("JumpCloudConnector authenticated: tenant=%s", self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("JumpCloudConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("JumpCloudConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="JumpCloud Users",
                supports_incremental=False,
                fields=[
                    "id", "username", "email", "firstname", "lastname",
                    "displayname", "activated", "suspended",
                    "account_locked", "mfa", "job_title", "department",
                    "organization", "manager",
                    "created", "updated",
                ],
            ),
            EntitySchema(
                entity_type="group",
                display_name="JumpCloud User Groups",
                supports_incremental=False,
                fields=[
                    "id", "name", "description", "type",
                    "memberCount",
                ],
            ),
            EntitySchema(
                entity_type="application",
                display_name="JumpCloud SSO Applications",
                supports_incremental=False,
                fields=[
                    "id", "name", "displayLabel", "ssoUrl",
                    "active", "beta", "created", "updated",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        config = self._entity_config(entity_type)
        yield from self._paginate_jumpcloud(
            endpoint=config["endpoint"],
            records_key=config.get("key"),
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
        """JumpCloud doesn't support incremental — full refresh."""
        def _generate() -> Iterator[RawRecord]:
            yield from self.extract_full(entity_type)

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{_API_BASE}/api/v1/systemusers",
                params={"limit": 1, "skip": 0},
                headers=self._headers(),
            )
            _ = resp.get("results", resp if isinstance(resp, list) else [])
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
            "x-api-key": self._api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _entity_config(self, entity_type: str) -> dict[str, str]:
        configs = {
            "user":        {"endpoint": "/api/v1/systemusers", "key": "results"},
            "group":       {"endpoint": "/api/v2/groups/user", "key": None},
            "application": {"endpoint": "/api/v2/applications",  "key": None},
        }
        if entity_type not in configs:
            raise ValueError(
                f"JumpCloudConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_jumpcloud(
        self,
        endpoint: str,
        records_key: str | None,
        entity_type: str,
    ) -> Iterator[RawRecord]:
        """
        Paginate JumpCloud using limit/skip.
        Some endpoints return { "results": [...], "totalCount": N },
        others return an array directly.
        """
        skip = 0

        while True:
            try:
                resp = self._get(
                    f"{_API_BASE}{endpoint}",
                    params={"limit": _PAGE_SIZE, "skip": skip},
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "JumpCloudConnector pagination error (endpoint=%s skip=%d): %s",
                    endpoint, skip, exc,
                )
                break

            # Handle both wrapped and direct array responses
            if isinstance(resp, list):
                records = resp
            elif records_key and records_key in resp:
                records = resp[records_key]
            else:
                records = resp.get("results", [])

            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            skip += len(records)

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        email = record.get("email")
        first = record.get("firstname", "")
        last = record.get("lastname", "")
        name = (
            record.get("displayLabel")     # application display label (most descriptive)
            or record.get("displayname")   # user display name
            or f"{first} {last}".strip()   # user first + last
            or record.get("name")          # group / application name
            or record.get("username")
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
