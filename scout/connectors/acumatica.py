"""
scout/connectors/acumatica.py — Production Acumatica ERP Connector (Sprint 38)

Acumatica is a cloud ERP platform popular in PE-backed mid-market companies
($10M–$200M ARR) in distribution, manufacturing, retail, and services.
It provides a REST/OData API with session-based or OAuth 2.0 authentication.

For Miragent:
  - Vendor spend analysis: supplier concentration risk
  - AP aging: outstanding bills and payment risk
  - Contractor vs. employee classification signals

Authentication:
  Acumatica supports two modes:
    1. Session login (username + password) — simpler, token in cookie/header
    2. OAuth 2.0 client credentials — recommended for server-to-server

  This connector uses the session login (cookie-based) by default,
  which is the most common integration pattern for Acumatica partners.

  Login endpoint: POST /entity/auth/login
  Logout:         POST /entity/auth/logout

API structure:
  Base: https://{instance}.acumatica.com/entity/Default/22.200.001/
  - /Vendor   → vendor records
  - /Employee → employee records

  OData filtering: ?$filter=...&$top=N&$skip=N&$select=...

Pagination:
  OData $top / $skip.
  No totalCount — keep paging until fewer than $top records returned.

Rate limits:
  Acumatica: no published hard limit; throttles around 10 concurrent sessions.
  We use 3/sec as a safe default for serial requests.

Entity types:
  - vendor    → Acumatica vendor records
  - employee  → Acumatica employee records
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

_PAGE_SIZE = 100  # Acumatica recommends 100-500 for OData


class AcumaticaConnector(ConnectorBase):
    """
    Production Acumatica ERP connector.

    Uses Acumatica's REST/OData endpoint API with session-based authentication.

    Credentials (auth_data keys):
        instance_url   — Base URL e.g. "https://acme.acumatica.com"
        username       — Acumatica username
        password       — Acumatica password
        company        — Acumatica company/branch name (optional)
        api_version    — API version, default "22.200.001"
    """

    CONNECTOR_ID = "acumatica"
    DISPLAY_NAME = "Acumatica ERP (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 3.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._instance_url: str = ""
        self._api_base: str = ""
        self._session_cookie: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Login via Acumatica's session endpoint.
        The server returns a cookie that we carry on subsequent requests.
        """
        auth = self.credentials.auth_data
        instance_url = auth.get("instance_url", "").rstrip("/")
        username = auth.get("username", "")
        password = auth.get("password", "")
        company = auth.get("company", "")
        api_version = auth.get("api_version", "22.200.001")

        if not all([instance_url, username, password]):
            logger.error(
                "AcumaticaConnector: missing 'instance_url', 'username', or 'password'"
            )
            return False

        self._instance_url = instance_url
        self._api_base = f"{instance_url}/entity/Default/{api_version}"

        payload: dict[str, Any] = {
            "name": username,
            "password": password,
        }
        if company:
            payload["company"] = company

        try:
            resp = self._http_client.post(
                f"{instance_url}/entity/auth/login",
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            resp.raise_for_status()

            # Acumatica returns a Set-Cookie header with the session token
            cookie = resp.headers.get("Set-Cookie", "")
            if not cookie:
                # Some versions embed the token in the response body
                body = resp.json()
                token = body.get("access_token") or body.get("token", "")
                if not token:
                    logger.error("AcumaticaConnector: no session cookie or token in login response")
                    return False
                self._session_cookie = f"ASPxRouteHandlerCookie={token}"
            else:
                # Extract the cookie value; take the first name=value pair
                self._session_cookie = cookie.split(";")[0]

            logger.info(
                "AcumaticaConnector authenticated: instance=%s tenant=%s",
                instance_url, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("AcumaticaConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("AcumaticaConnector auth error: %s", exc)
            return False

    def logout(self) -> None:
        """Politely end the session (frees up Acumatica concurrent session slot)."""
        try:
            self._http_client.post(
                f"{self._instance_url}/entity/auth/logout",
                headers=self._headers(),
            )
        except Exception:
            pass  # Best-effort

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Acumatica Vendors",
                supports_incremental=True,
                fields=[
                    "VendorID", "VendorName", "VendorClass", "Status",
                    "CurrencyID", "PaymentMethodID", "PaymentLeadTimeInDays",
                    "TaxZoneID", "Terms", "NoteID",
                    "LastModifiedDateTime",
                ],
            ),
            EntitySchema(
                entity_type="employee",
                display_name="Acumatica Employees",
                supports_incremental=True,
                fields=[
                    "EmployeeID", "Status", "EmployeeClass",
                    "DepartmentID", "PositionID", "ReportsToID",
                    "CalendarID", "HoursValidation",
                    "LastModifiedDateTime",
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
        Incremental via OData $filter on LastModifiedDateTime.
        Format: LastModifiedDateTime gt 2026-01-01T00:00:00
        """
        endpoint = self._entity_endpoint(entity_type)
        since_str = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S")
        odata_filter = f"LastModifiedDateTime gt {since_str}"

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
                f"{self._api_base}/Vendor",
                params={"$top": 1},
                headers=self._headers(),
            )
            _ = resp  # any successful response
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
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._session_cookie:
            h["Cookie"] = self._session_cookie
        return h

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "vendor":   "/Vendor",
            "employee": "/Employee",
        }
        if entity_type not in endpoints:
            raise ValueError(
                f"AcumaticaConnector does not support entity_type='{entity_type}'. "
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
        Paginate Acumatica OData endpoint using $top/$skip.
        No totalCount — stop when fewer records than $top are returned.
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
                    "AcumaticaConnector pagination error (endpoint=%s skip=%d): %s",
                    endpoint, skip, exc,
                )
                break

            # OData returns either a direct list or {"value": [...]}
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
            source_id = _unwrap(record.get("VendorID")) or ""
            name = _unwrap(record.get("VendorName")) or None
            email = None
        else:  # employee
            source_id = _unwrap(record.get("EmployeeID")) or ""
            name = _unwrap(record.get("EmployeeID")) or None
            email = _unwrap(record.get("Email")) or None

        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.tenant_id,
            payload=record,
            email_hint=email,
            name_hint=name,
        )


def _unwrap(field: Any) -> str | None:
    """
    Acumatica OData fields are often wrapped: {"value": "...", "type": "string"}.
    This helper extracts the value, returning None for missing/null fields.
    """
    if field is None:
        return None
    if isinstance(field, dict):
        v = field.get("value")
        return str(v) if v is not None else None
    return str(field) if field else None
