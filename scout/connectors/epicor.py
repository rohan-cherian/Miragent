"""
scout/connectors/epicor.py — Production Epicor ERP Connector (Sprint 38)

Epicor is an industry-specific ERP platform dominant in manufacturing,
distribution, and retail ($20M–$500M ARR). Common in PE portfolios that
hold industrial, consumer products, and supply-chain businesses.

For Miragent:
  - Vendor/supplier concentration and spend signals
  - Employee roster for offboarding verification
  - Purchase order pipeline (vendor renewal/re-negotiation windows)

Authentication:
  Epicor REST API v2 uses Basic Authentication (username:password encoded
  as Base64) passed in the Authorization header. OAuth 2.0 is available
  on Epicor Kinetic (cloud edition) via Azure AD.

  This connector supports both:
    auth_mode = "basic"   → Authorization: Basic <b64(user:pass)>
    auth_mode = "bearer"  → Authorization: Bearer <token>

API structure:
  Base: https://{server}/api/erp/v2/{company}/
  - /Erp.Vendor    → vendor master
  - /Erp.Employee  → employee master

  OData style: ?$top=N&$skip=N&$filter=...&$select=...

Pagination:
  OData $top / $skip pattern. Stop when records < $top.

Rate limits:
  Epicor: no published hard limit per request type.
  We use 3/sec as a conservative default for server-hosted deployments.

Entity types:
  - vendor    → Epicor vendor records
  - employee  → Epicor employee records
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

_PAGE_SIZE = 100


class EpicorConnector(ConnectorBase):
    """
    Production Epicor ERP connector.

    Credentials (auth_data keys — Basic auth):
        server_url   — Base server URL e.g. "https://epicor.acme.com"
        company      — Epicor company code e.g. "ACME"
        username     — Epicor username
        password     — Epicor password
        auth_mode    — "basic" (default) or "bearer"

    Credentials (auth_data keys — Bearer token):
        server_url   — Base server URL
        company      — Epicor company code
        access_token — Bearer token
        auth_mode    — "bearer"
    """

    CONNECTOR_ID = "epicor"
    DISPLAY_NAME = "Epicor ERP (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 3.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_base: str = ""
        self._auth_header: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        import base64

        auth = self.credentials.auth_data
        server_url = auth.get("server_url", "").rstrip("/")
        company = auth.get("company", "")
        auth_mode = auth.get("auth_mode", "basic")

        if not all([server_url, company]):
            logger.error("EpicorConnector: missing 'server_url' or 'company'")
            return False

        self._api_base = f"{server_url}/api/erp/v2/{company}"

        if auth_mode == "basic":
            username = auth.get("username", "")
            password = auth.get("password", "")
            if not all([username, password]):
                logger.error("EpicorConnector: missing 'username' or 'password' for basic auth")
                return False
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._auth_header = f"Basic {encoded}"
        elif auth_mode == "bearer":
            token = auth.get("access_token", "")
            if not token:
                logger.error("EpicorConnector: missing 'access_token' for bearer auth")
                return False
            self._auth_header = f"Bearer {token}"
        else:
            logger.error("EpicorConnector: unknown auth_mode '%s'", auth_mode)
            return False

        # Validate by fetching a single vendor record
        try:
            resp = self._http_client.get(
                f"{self._api_base}/Erp.Vendor",
                params={"$top": 1},
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info(
                "EpicorConnector authenticated: server=%s company=%s tenant=%s",
                server_url, company, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("EpicorConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("EpicorConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Epicor Vendors",
                supports_incremental=True,
                fields=[
                    "VendorNum", "Name", "VendorID", "VendorType",
                    "CurrencyCode", "TermsCode", "PurPoint",
                    "GlbCompany", "GroupCode",
                    "ChangeDate",
                ],
            ),
            EntitySchema(
                entity_type="employee",
                display_name="Epicor Employees",
                supports_incremental=True,
                fields=[
                    "EmpID", "FirstName", "LastName", "Name",
                    "EmpRoleCode", "DeptDescription",
                    "SupervisorID", "Phone", "EMailAddress",
                    "ChangeDate",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        endpoint = self._entity_endpoint(entity_type)
        yield from self._paginate_odata(endpoint=endpoint, entity_type=entity_type)

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Incremental via OData $filter on ChangeDate.
        Format: ChangeDate gt 2026-01-01T00:00:00
        """
        endpoint = self._entity_endpoint(entity_type)
        since_str = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S")
        odata_filter = f"ChangeDate gt {since_str}"

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_odata(
                endpoint=endpoint,
                entity_type=entity_type,
                extra_filter=odata_filter,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": since_str},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{self._api_base}/Erp.Vendor",
                params={"$top": 1},
                headers=self._headers(),
            )
            _ = resp
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

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "vendor":   "/Erp.Vendor",
            "employee": "/Erp.Employee",
        }
        if entity_type not in endpoints:
            raise ValueError(
                f"EpicorConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(endpoints)}"
            )
        return endpoints[entity_type]

    def _paginate_odata(
        self,
        endpoint: str,
        entity_type: str,
        extra_filter: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Epicor OData endpoint using $top/$skip.
        Response: {"value": [...]} or a direct array.
        """
        skip = 0

        while True:
            params: dict[str, Any] = {
                "$top": _PAGE_SIZE,
                "$skip": skip,
            }
            if extra_filter:
                params["$filter"] = extra_filter

            try:
                resp = self._get(
                    f"{self._api_base}{endpoint}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "EpicorConnector pagination error (endpoint=%s skip=%d): %s",
                    endpoint, skip, exc,
                )
                break

            if isinstance(resp, list):
                records = resp
            else:
                records = resp.get("value", [])

            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            skip += len(records)

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        if entity_type == "vendor":
            source_id = str(record.get("VendorNum", ""))
            name = record.get("Name") or None
            email = None
        else:  # employee
            source_id = str(record.get("EmpID", ""))
            first = record.get("FirstName", "")
            last = record.get("LastName", "")
            name = (
                record.get("Name")
                or f"{first} {last}".strip()
                or None
            )
            email = record.get("EMailAddress") or None

        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.tenant_id,
            payload=record,
            email_hint=email,
            name_hint=name,
        )
