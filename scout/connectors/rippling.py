"""
scout/connectors/rippling.py — Production Rippling HRIS/IT Connector (Sprint 29)

Rippling is the fastest-growing HR+IT platform in the PE mid-market. Unlike
Workday or BambooHR, Rippling combines HRIS, payroll, device management, and
SaaS app provisioning in a single platform — making it uniquely powerful for
the Miragent cross-system graph. A single Rippling connector surfaces employee
data, device assignments, and app access in one call.

Authentication:
  Rippling uses OAuth 2.0 Authorization Code flow for third-party apps, or
  API key (Bearer token) for direct integrations. PE portfolio companies
  typically issue a service account API key from their Rippling admin console.

  Header: Authorization: Bearer {api_key}

API structure:
  Base URL: https://api.rippling.com/platform/api/
  - /employees             → all employees with HR + device info
  - /departments           → org structure
  - /roles                 → job roles and levels
  - /leaves                → leave requests and absences
  - /devices               → assigned devices per employee

Rate limits:
  Rippling enforces 60 requests/minute per API key. We use 0.9/sec (54/min)
  to stay below the limit with burst headroom.

Entity types:
  - employee    → full employee record including role, status, manager
  - department  → org structure for graph construction
  - device      → endpoint devices assigned to employees (for offboarding)
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

_BASE_URL = "https://api.rippling.com/platform/api"
_PAGE_SIZE = 200  # Rippling supports up to 200 per page


class RipplingConnector(ConnectorBase):
    """
    Production Rippling HRIS+IT connector.

    Extracts employees, org structure, and device assignments from Rippling.
    The device entity type is especially valuable for Miragent's offboarding
    workflow — we can surface unreclaimed devices for departed employees.

    Credentials (auth_data keys):
        api_key — Rippling service account API key (from Admin → API)
    """

    CONNECTOR_ID = "rippling"
    DISPLAY_NAME = "Rippling HRIS + IT (Production)"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 0.9  # 54/min — safely below Rippling's 60/min limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_key: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Validate the API key by fetching the current user's identity.

        Uses /me endpoint for a fast, low-cost auth check.
        """
        api_key = self.credentials.auth_data.get("api_key", "")
        if not api_key:
            logger.error(
                "RipplingConnector: missing required auth_data key 'api_key'"
            )
            return False

        self._api_key = api_key

        try:
            resp = self._http_client.get(
                f"{_BASE_URL}/me",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "RipplingConnector authenticated: company=%s tenant=%s",
                data.get("company", {}).get("name", "unknown"),
                self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                logger.error(
                    "RipplingConnector: API key rejected (401). "
                    "Verify key is active and has read:employees scope. "
                    "tenant=%s", self.tenant_id
                )
            else:
                logger.error(
                    "RipplingConnector.authenticate HTTP %d: %s",
                    exc.response.status_code, exc,
                )
            return False
        except Exception as exc:
            logger.exception("RipplingConnector.authenticate error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="employee",
                display_name="Rippling Employees",
                supports_incremental=True,
                fields=[
                    "id", "userId", "workEmail", "personalEmail",
                    "firstName", "lastName", "preferredFirstName",
                    "title", "department", "role", "level",
                    "managerId", "managerEmail",
                    "startDate", "endDate", "employmentType",
                    "employmentStatus", "flsaStatus",
                    "workLocation", "remoteStatus",
                    "paySchedule", "compensationType",
                ],
            ),
            EntitySchema(
                entity_type="department",
                display_name="Rippling Departments",
                supports_incremental=False,
                fields=["id", "name", "parentId", "headId", "headEmail"],
            ),
            EntitySchema(
                entity_type="device",
                display_name="Rippling Devices",
                supports_incremental=True,
                fields=[
                    "id", "serialNumber", "model", "type",
                    "osVersion", "assignedTo", "assignedToEmail",
                    "enrolledAt", "lastCheckin", "status",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Full extraction using cursor-based pagination.

        Rippling uses cursor pagination (not offset). The response includes
        a `next` cursor value — pass it as `cursor` in the next request.
        When `next` is null, all pages have been fetched.
        """
        endpoint_map = {
            "employee": "/employees",
            "department": "/departments",
            "device": "/devices",
        }
        if entity_type not in endpoint_map:
            raise ValueError(
                f"RipplingConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(endpoint_map)}"
            )

        yield from self._paginate_rippling(
            endpoint=endpoint_map[entity_type],
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
        Incremental extraction using Rippling's updatedAfter filter.

        Rippling supports `updatedAfter` as an ISO 8601 timestamp query
        parameter on the /employees endpoint. This gives us only records
        modified (including status changes to Terminated) since the cursor.
        """
        endpoint_map = {
            "employee": "/employees",
            "department": "/departments",
            "device": "/devices",
        }
        if entity_type not in endpoint_map:
            raise ValueError(
                f"RipplingConnector: unsupported entity_type '{entity_type}'"
            )

        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_rippling(
                endpoint=endpoint_map[entity_type],
                entity_type=entity_type,
                extra_params={"updatedAfter": since_iso},
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"updated_after": since_iso},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._http_client.get(
                f"{_BASE_URL}/me",
                headers=self._headers(),
            )
            resp.raise_for_status()
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
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _paginate_rippling(
        self,
        endpoint: str,
        entity_type: str,
        extra_params: dict[str, Any] | None = None,
    ) -> Iterator[RawRecord]:
        """
        Paginate Rippling results using cursor-based pagination.

        Rippling response structure:
          {
            "data": [...records...],
            "next": "cursor_token_or_null"
          }

        We pass `cursor=<next>` until next is null.
        """
        cursor_token: str | None = None
        page = 0

        while True:
            params: dict[str, Any] = {"limit": _PAGE_SIZE}
            if cursor_token:
                params["cursor"] = cursor_token
            if extra_params:
                params.update(extra_params)

            try:
                resp = self._get(
                    f"{_BASE_URL}{endpoint}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "RipplingConnector pagination error (page=%d endpoint=%s): %s",
                    page, endpoint, exc,
                )
                break

            records = resp.get("data", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            cursor_token = resp.get("next")
            if not cursor_token or not records:
                break
            page += 1

    def _to_raw_record(
        self, entity_type: str, record: dict[str, Any]
    ) -> RawRecord:
        """Convert a Rippling record to a RawRecord."""
        source_id = str(
            record.get("id") or record.get("userId") or record.get("serialNumber", "")
        )
        email = (
            record.get("workEmail")
            or record.get("assignedToEmail")
            or record.get("headEmail")
        )
        # Build name from firstName + lastName or from name field
        name = (
            f"{record.get('firstName', '')} {record.get('lastName', '')}".strip()
            or record.get("name")
            or record.get("model")  # device model as name fallback
        ) or None

        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.tenant_id,
            payload=record,
            email_hint=email,
            name_hint=name,
        )
