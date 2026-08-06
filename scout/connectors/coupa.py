"""
scout/connectors/coupa.py — Production Coupa Connector (Sprint 36)

Coupa is a comprehensive Business Spend Management (BSM) platform used by
PE-backed mid-to-large enterprises for procurement, invoicing, and expense.
Competes with SAP Ariba and Oracle Procurement.

For Miragent:
  - Vendor master data (supplier risk, payment terms, approval status)
  - Purchase order tracking (unapproved POs, expired POs)
  - Invoice approval status (blocked invoices, duplicate payment risk)
  - Spend analytics by category/department

Authentication:
  Coupa uses OAuth 2.0 Client Credentials with a long-lived client secret.
  Token endpoint: https://{instance}.coupahost.com/oauth2/token

API structure:
  Base: https://{instance}.coupahost.com/api
  - /suppliers              → vendor/supplier master
  - /purchase_orders        → PO records
  - /invoices               → AP invoices
  - /users                  → Coupa user accounts

Pagination:
  Coupa uses offset + limit with a `has_more` or checks record count.
  Response: [ ...records... ] (array, not object)
  Uses Link header for pagination: Link: <url>; rel="next"

Rate limits:
  Coupa: 1000 requests/hour for API token access.
  We use 0.25/sec (15/min) as a conservative default.

Entity types:
  - supplier       → vendor/supplier records
  - purchase_order → purchase order records
  - invoice        → AP invoice records
  - user           → Coupa user accounts
"""

import logging
import re
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

_PAGE_SIZE = 50  # Coupa default max
_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class CoupaConnector(ConnectorBase):
    """
    Production Coupa Business Spend Management connector.

    Credentials (auth_data keys):
        instance      — Coupa instance name, e.g. "acme" (→ acme.coupahost.com)
        client_id     — OAuth client ID
        client_secret — OAuth client secret
        scope         — OAuth scope (default: "core.common.read")
    """

    CONNECTOR_ID = "coupa"
    DISPLAY_NAME = "Coupa Business Spend Management (Production)"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 0.25

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._base_url: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        instance = auth.get("instance", "")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        scope = auth.get("scope", "core.common.read")

        if not all([instance, client_id, client_secret]):
            logger.error("CoupaConnector: missing 'instance', 'client_id', or 'client_secret'")
            return False

        self._base_url = f"https://{instance}.coupahost.com"
        token_url = f"{self._base_url}/oauth2/token"

        try:
            resp = self._http_client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("CoupaConnector: no access_token in response")
                return False
            self._access_token = token
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            logger.info("CoupaConnector authenticated: instance=%s tenant=%s", instance, self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("CoupaConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("CoupaConnector auth error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        if time.time() > self._token_expires_at - 300:
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="supplier",
                display_name="Coupa Suppliers",
                supports_incremental=True,
                fields=[
                    "id", "name", "number", "status", "primary_contact",
                    "payment_term", "default_currency",
                    "tax_id", "allow_cxml_invoicing",
                    "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="purchase_order",
                display_name="Coupa Purchase Orders",
                supports_incremental=True,
                fields=[
                    "id", "po_number", "status", "supplier",
                    "requester", "ship_to_address",
                    "order_lines", "total", "currency",
                    "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="Coupa Invoices",
                supports_incremental=True,
                fields=[
                    "id", "invoice_number", "status", "supplier",
                    "gross_total", "currency",
                    "invoice_date", "due_date",
                    "payment_status", "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="user",
                display_name="Coupa Users",
                supports_incremental=True,
                fields=[
                    "id", "login", "email", "firstname", "lastname",
                    "status", "employee_number",
                    "default_locale", "roles",
                    "created_at", "updated_at",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        endpoint = self._entity_endpoint(entity_type)
        yield from self._paginate_coupa(endpoint=endpoint, entity_type=entity_type)

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Incremental via Coupa's updated_at filter.
        Format: ?filters[updated_at][gt]=ISO
        """
        endpoint = self._entity_endpoint(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S")

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_coupa(
                endpoint=endpoint,
                entity_type=entity_type,
                updated_after=since_iso,
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
            self._refresh_if_needed()
            resp = self._get(
                f"{self._base_url}/api/suppliers",
                params={"limit": 1, "offset": 0},
                headers=self._headers(),
            )
            # Coupa returns an array
            _ = resp if isinstance(resp, list) else []
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
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-COUPA-API-VERSION": "48",
        }

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "supplier":       "/api/suppliers",
            "purchase_order": "/api/purchase_orders",
            "invoice":        "/api/invoices",
            "user":           "/api/users",
        }
        if entity_type not in endpoints:
            raise ValueError(
                f"CoupaConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(endpoints)}"
            )
        return endpoints[entity_type]

    def _paginate_coupa(
        self,
        endpoint: str,
        entity_type: str,
        updated_after: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Coupa API using offset/limit.
        Coupa returns JSON arrays; stops when fewer than page_size returned.
        """
        self._refresh_if_needed()
        offset = 0

        while True:
            params: dict[str, Any] = {"limit": _PAGE_SIZE, "offset": offset}
            if updated_after:
                params["filters[updated_at][gt]"] = updated_after

            try:
                resp = self._get(
                    f"{self._base_url}{endpoint}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("CoupaConnector pagination error (endpoint=%s): %s", endpoint, exc)
                break

            # Coupa returns either an array or wraps in a key
            records = resp if isinstance(resp, list) else resp.get("data", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            offset += len(records)

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        email = (
            record.get("email")
            or record.get("login")
            or (record.get("primary_contact") or {}).get("email")
        )
        name = (
            record.get("name")
            or f"{record.get('firstname', '')} {record.get('lastname', '')}".strip()
            or record.get("po_number")
            or record.get("invoice_number")
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
