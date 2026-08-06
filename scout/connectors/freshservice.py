"""
scout/connectors/freshservice.py — Production Freshservice Connector (Sprint 35)

Freshservice is a cloud-based ITSM platform popular with PE-backed mid-market
companies that want simpler, cheaper ServiceNow alternative. Used heavily in
IT onboarding/offboarding workflows and asset tracking.

For Miragent, Freshservice surfaces:
  - Offboarding ticket completeness (HR service desk tickets)
  - IT access requests (who requested what systems)
  - Asset assignments (who has which equipment/licenses)
  - Incident trends per department (operational risk signal)

Authentication:
  Freshservice uses HTTP Basic Auth with an API key as the username
  and any value (e.g., "X") as the password.
  Header: Authorization: Basic base64("{api_key}:X")

API structure:
  Base: https://{domain}.freshservice.com
  - /api/v2/tickets         → support tickets
  - /api/v2/requesters      → end-users / requesters
  - /api/v2/agents          → IT agents
  - /api/v2/assets          → IT asset inventory

Pagination:
  Freshservice uses page + per_page.
  Response includes: { "tickets": [...] } — no explicit total.
  Stops when returned count < per_page.

Rate limits:
  Freshservice: 1000 requests/hour on most plans.
  We use 2/sec (120/min) as a safe default.

Entity types:
  - ticket     → support/service tickets
  - requester  → end-user accounts (employees who submit tickets)
  - agent      → Freshservice agent accounts
  - asset      → IT asset records
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

_PAGE_SIZE = 100  # Freshservice max per_page


class FreshserviceConnector(ConnectorBase):
    """
    Production Freshservice ITSM connector.

    Uses HTTP Basic Auth with API key.

    Credentials (auth_data keys):
        domain    — Freshservice domain, e.g. "acme" (→ acme.freshservice.com)
        api_key   — Freshservice API key
    """

    CONNECTOR_ID = "freshservice"
    DISPLAY_NAME = "Freshservice ITSM (Production)"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 2.0  # 120/min — well within 1000/hr limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._auth_header: str = ""
        self._base_url: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Authenticate using Freshservice API key as Basic Auth username.
        Password is always "X" (Freshservice convention).
        """
        auth = self.credentials.auth_data
        domain = auth.get("domain", "")
        api_key = auth.get("api_key", "")

        if not domain:
            logger.error("FreshserviceConnector: missing required auth_data key 'domain'")
            return False
        if not api_key:
            logger.error("FreshserviceConnector: missing required auth_data key 'api_key'")
            return False

        self._base_url = f"https://{domain}.freshservice.com"
        raw = f"{api_key}:X"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()

        # Validate by fetching 1 ticket
        try:
            resp = self._http_client.get(
                f"{self._base_url}/api/v2/tickets",
                params={"page": 1, "per_page": 1},
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info(
                "FreshserviceConnector authenticated: domain=%s tenant=%s",
                domain, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("FreshserviceConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("FreshserviceConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="ticket",
                display_name="Freshservice Tickets",
                supports_incremental=True,
                fields=[
                    "id", "subject", "description", "status", "priority", "type",
                    "source", "requester_id", "responder_id", "group_id",
                    "category", "sub_category", "tags",
                    "due_by", "fr_due_by", "is_escalated",
                    "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="requester",
                display_name="Freshservice Requesters",
                supports_incremental=True,
                fields=[
                    "id", "first_name", "last_name", "email",
                    "mobile", "phone", "department_ids",
                    "location_id", "is_agent", "active",
                    "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="agent",
                display_name="Freshservice Agents",
                supports_incremental=True,
                fields=[
                    "id", "first_name", "last_name", "email",
                    "phone", "mobile", "active", "role_ids",
                    "group_ids", "department_ids", "location_id",
                    "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="asset",
                display_name="Freshservice Assets",
                supports_incremental=True,
                fields=[
                    "id", "name", "description", "asset_type_id",
                    "asset_tag", "impact", "used_by",
                    "location_id", "department_id",
                    "acquisition_date", "expiry_date",
                    "created_at", "updated_at",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        config = self._entity_config(entity_type)
        yield from self._paginate_freshservice(
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
        Incremental via Freshservice's updated_since filter.
        Format: ?updated_since=2026-01-01T00:00:00Z (ISO 8601)
        """
        config = self._entity_config(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_freshservice(
                endpoint=config["endpoint"],
                records_key=config["key"],
                entity_type=entity_type,
                updated_since=since_iso,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": since_iso},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{self._base_url}/api/v2/tickets",
                params={"page": 1, "per_page": 1},
                headers=self._headers(),
            )
            _ = resp.get("tickets", [])
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
            "ticket":    {"endpoint": "/api/v2/tickets",    "key": "tickets"},
            "requester": {"endpoint": "/api/v2/requesters", "key": "requesters"},
            "agent":     {"endpoint": "/api/v2/agents",     "key": "agents"},
            "asset":     {"endpoint": "/api/v2/assets",     "key": "assets"},
        }
        if entity_type not in configs:
            raise ValueError(
                f"FreshserviceConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_freshservice(
        self,
        endpoint: str,
        records_key: str,
        entity_type: str,
        updated_since: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Freshservice API with page/per_page.
        Stops when returned record count < per_page.
        """
        page = 1

        while True:
            params: dict[str, Any] = {"page": page, "per_page": _PAGE_SIZE}
            if updated_since:
                params["updated_since"] = updated_since

            try:
                resp = self._get(
                    f"{self._base_url}{endpoint}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "FreshserviceConnector pagination error (endpoint=%s page=%d): %s",
                    endpoint, page, exc,
                )
                break

            records = resp.get(records_key, [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            page += 1

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        email = record.get("email")
        first = record.get("first_name", "")
        last = record.get("last_name", "")
        name = (
            f"{first} {last}".strip()
            or record.get("name")
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
