"""
scout/connectors/sap.py — Production SAP Business One / S/4HANA Connector (Sprint 32)

SAP is the ERP backbone for PE-backed industrials, manufacturing, and
distribution companies. Two major SAP variants appear in the mid-market:

  SAP Business One (B1) — for companies $10M–$150M ARR
    REST-based Service Layer API. Session cookie auth.
    Endpoints: /b1s/v1/BusinessPartners, /Employees, /PurchaseOrders, etc.

  SAP S/4HANA Cloud — for companies $150M+ moving up-market
    OData v4 API via SAP's API Business Hub.
    Auth: OAuth 2.0 Client Credentials.

This connector handles BOTH variants. The auth_mode credential key selects:
  auth_mode = "b1"      → SAP Business One Service Layer
  auth_mode = "s4hana"  → SAP S/4HANA OData API

Authentication (B1):
  POST /b1s/v1/Login with CompanyDB, UserName, Password → session cookie
  All subsequent requests send: Cookie: B1SESSION={session_id}

Authentication (S/4HANA):
  POST to SAP OAuth server → Bearer token
  All requests: Authorization: Bearer {token}

API structure (B1):
  Base: https://{host}:{port}/b1s/v1/
  - /BusinessPartners?$filter=CardType eq 'cSupplier'   → vendors
  - /BusinessPartners?$filter=CardType eq 'cCustomer'   → customers
  - /Employees                                           → employees
  - /PurchaseOrders                                      → purchase orders
  - /Invoices                                            → A/R invoices
  - /PurchaseInvoices                                    → A/P invoices

Rate limits:
  SAP B1 Service Layer enforces no hard rate limit but recommends < 50 req/sec.
  S/4HANA enforces 1000 req/min. We use 10/sec for both (conservative).

Entity types:
  - vendor          → supplier master data (BusinessPartner where CardType=Supplier)
  - customer        → customer master data (BusinessPartner where CardType=Customer)
  - employee        → HR employee records
  - purchase_order  → PO data for spend analysis
  - invoice         → A/R and A/P invoices
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

_PAGE_SIZE = 100  # SAP B1 default page size; S/4HANA supports up to 1000


class SAPConnector(ConnectorBase):
    """
    Production SAP connector supporting Business One (B1) and S/4HANA.

    Automatically selects the correct API flavor based on auth_mode in credentials.
    Handles session cookie auth (B1) and Bearer token auth (S/4HANA).

    Credentials (auth_data keys for B1):
        auth_mode     — "b1" or "s4hana"
        host          — SAP server hostname/IP
        port          — Service Layer port (default 50000 for B1)
        company_db    — SAP company database name
        username      — SAP service account username
        password      — SAP service account password

    Credentials (auth_data keys for S/4HANA):
        auth_mode     — "s4hana"
        host          — S/4HANA API host (e.g., "my-api.s4hana.ondemand.com")
        client_id     — OAuth client ID
        client_secret — OAuth client secret
        token_url     — OAuth token endpoint URL
    """

    CONNECTOR_ID = "sap"
    DISPLAY_NAME = "SAP Business One / S4HANA (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 10.0  # safe for both B1 and S/4HANA

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._auth_mode: str = ""       # "b1" or "s4hana"
        self._session_id: str = ""      # B1 session cookie
        self._access_token: str = ""    # S/4HANA Bearer token
        self._token_expires_at: float = 0.0
        self._base_url: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """Route to B1 or S/4HANA auth based on auth_mode."""
        auth = self.credentials.auth_data
        self._auth_mode = auth.get("auth_mode", "b1")

        if self._auth_mode == "b1":
            return self._authenticate_b1(auth)
        elif self._auth_mode == "s4hana":
            return self._authenticate_s4hana(auth)
        else:
            logger.error(
                "SAPConnector: unknown auth_mode '%s'. Use 'b1' or 's4hana'.",
                self._auth_mode,
            )
            return False

    def _authenticate_b1(self, auth: dict) -> bool:
        """
        SAP Business One Service Layer session auth.
        POST /b1s/v1/Login → { "SessionId": "abc123" }
        """
        host = auth.get("host", "")
        port = auth.get("port", "50000")
        company_db = auth.get("company_db", "")
        username = auth.get("username", "")
        password = auth.get("password", "")

        if not all([host, company_db, username, password]):
            logger.error(
                "SAPConnector B1: missing required auth_data keys "
                "(host, company_db, username, password)"
            )
            return False

        self._base_url = f"https://{host}:{port}/b1s/v1"

        try:
            resp = self._http_client.post(
                f"{self._base_url}/Login",
                json={
                    "CompanyDB": company_db,
                    "UserName": username,
                    "Password": password,
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._session_id = data.get("SessionId", "")
            if not self._session_id:
                logger.error("SAPConnector B1: no SessionId in login response")
                return False
            logger.info(
                "SAPConnector B1 authenticated: host=%s db=%s tenant=%s",
                host, company_db, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "SAPConnector B1 login HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("SAPConnector B1 authenticate error: %s", exc)
            return False

    def _authenticate_s4hana(self, auth: dict) -> bool:
        """
        SAP S/4HANA OAuth 2.0 Client Credentials flow.
        """
        host = auth.get("host", "")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        token_url = auth.get("token_url", "")

        if not all([host, client_id, client_secret, token_url]):
            logger.error(
                "SAPConnector S/4HANA: missing required auth_data keys "
                "(host, client_id, client_secret, token_url)"
            )
            return False

        self._base_url = f"https://{host}"

        try:
            resp = self._http_client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

            if not self._access_token:
                logger.error("SAPConnector S/4HANA: no access_token in response")
                return False

            logger.info(
                "SAPConnector S/4HANA authenticated: host=%s tenant=%s",
                host, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "SAPConnector S/4HANA token HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("SAPConnector S/4HANA authenticate error: %s", exc)
            return False

    def _refresh_s4hana_if_needed(self) -> None:
        if self._auth_mode == "s4hana" and time.time() > self._token_expires_at - 300:
            logger.debug("SAPConnector: refreshing S/4HANA token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="SAP Vendors / Suppliers",
                supports_incremental=True,
                fields=[
                    "CardCode", "CardName", "CardType", "GroupCode",
                    "CreditLimit", "Balance", "Currency",
                    "Phone1", "Phone2", "EmailAddress",
                    "ContactPersons", "Addresses",
                    "PayTermsGrpCode", "VatLiable",
                    "UpdateDate", "CreateDate",
                ],
            ),
            EntitySchema(
                entity_type="customer",
                display_name="SAP Customers",
                supports_incremental=True,
                fields=[
                    "CardCode", "CardName", "CardType", "GroupCode",
                    "CreditLimit", "Balance", "Currency",
                    "Phone1", "EmailAddress", "ContactPersons",
                    "SalesPersonCode", "Territory", "Industry",
                    "UpdateDate", "CreateDate",
                ],
            ),
            EntitySchema(
                entity_type="employee",
                display_name="SAP Employees",
                supports_incremental=True,
                fields=[
                    "EmployeeID", "FirstName", "LastName", "MiddleName",
                    "JobTitle", "Department", "Branch", "WorkStreet",
                    "WorkCity", "WorkCountry", "HomePhone", "OfficePhone",
                    "Email", "EmployeeStatus", "StartDate", "TerminationDate",
                    "Manager", "Position",
                ],
            ),
            EntitySchema(
                entity_type="purchase_order",
                display_name="SAP Purchase Orders",
                supports_incremental=True,
                fields=[
                    "DocEntry", "DocNum", "DocDate", "DocDueDate",
                    "CardCode", "CardName", "NumAtCard",
                    "DocTotal", "VatSum", "Currency",
                    "DocumentStatus", "DocumentLines",
                    "UpdateDate",
                ],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="SAP Invoices (A/R + A/P)",
                supports_incremental=True,
                fields=[
                    "DocEntry", "DocNum", "DocDate", "DueDate",
                    "CardCode", "CardName",
                    "DocTotal", "PaidToDate", "DocumentStatus",
                    "Currency", "DocumentLines",
                    "UpdateDate",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """Full extraction using SAP OData $skip/$top pagination."""
        entity_map = {
            "vendor":         ("BusinessPartners", "CardType eq 'cSupplier'"),
            "customer":       ("BusinessPartners", "CardType eq 'cCustomer'"),
            "employee":       ("Employees", ""),
            "purchase_order": ("PurchaseOrders", ""),
            "invoice":        ("Invoices", ""),
        }
        if entity_type not in entity_map:
            raise ValueError(
                f"SAPConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(entity_map)}"
            )

        collection, base_filter = entity_map[entity_type]
        yield from self._paginate_odata(
            collection=collection,
            entity_type=entity_type,
            odata_filter=base_filter,
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
        Incremental extraction using SAP's UpdateDate filter.

        SAP OData supports $filter=UpdateDate ge '20260101' for all entities.
        Date format is YYYYMMDD (no dashes) in SAP B1; ISO for S/4HANA.
        """
        entity_map = {
            "vendor":         ("BusinessPartners", "CardType eq 'cSupplier'"),
            "customer":       ("BusinessPartners", "CardType eq 'cCustomer'"),
            "employee":       ("Employees", ""),
            "purchase_order": ("PurchaseOrders", ""),
            "invoice":        ("Invoices", ""),
        }
        if entity_type not in entity_map:
            raise ValueError(
                f"SAPConnector: unsupported entity_type '{entity_type}'"
            )

        since_dt = cursor.last_extracted_at
        # SAP B1 uses YYYYMMDD format; S/4HANA uses ISO
        if self._auth_mode == "b1":
            since_str = since_dt.strftime("%Y%m%d")
            date_filter = f"UpdateDate ge '{since_str}'"
        else:
            since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            date_filter = f"UpdateDate ge {since_str}"

        collection, base_filter = entity_map[entity_type]
        combined_filter = (
            f"{base_filter} and {date_filter}" if base_filter else date_filter
        )

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_odata(
                collection=collection,
                entity_type=entity_type,
                odata_filter=combined_filter,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": since_str, "mode": self._auth_mode},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        """Lightweight ping via $top=1 on Employees."""
        start = time.monotonic()
        try:
            self._refresh_s4hana_if_needed()
            resp = self._get(
                f"{self._base_url}/Employees",
                params={"$top": 1},
                headers=self._headers(),
            )
            _ = resp.get("value", resp)
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
        if self._auth_mode == "b1":
            return {
                "Cookie": f"B1SESSION={self._session_id}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            return {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

    def _paginate_odata(
        self,
        collection: str,
        entity_type: str,
        odata_filter: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate SAP OData collections using $skip/$top.

        SAP B1 response structure:
          { "value": [...records...] }

        We increment $skip until an empty page is returned.
        """
        self._refresh_s4hana_if_needed()
        skip = 0

        while True:
            params: dict[str, Any] = {"$top": _PAGE_SIZE, "$skip": skip}
            if odata_filter:
                params["$filter"] = odata_filter

            try:
                resp = self._get(
                    f"{self._base_url}/{collection}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "SAPConnector pagination error (collection=%s skip=%d): %s",
                    collection, skip, exc,
                )
                break

            # SAP OData wraps results in "value"; direct array also handled
            records = resp.get("value", resp if isinstance(resp, list) else [])
            if not records:
                break

            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            skip += _PAGE_SIZE

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        """Convert a SAP record to RawRecord with appropriate field mapping."""
        # Source ID varies by entity type
        source_id = str(
            record.get("CardCode")
            or record.get("EmployeeID")
            or record.get("DocEntry")
            or record.get("DocNum")
            or ""
        )

        # Email extraction
        email = (
            record.get("EmailAddress")
            or record.get("Email")
            or record.get("email")
        )

        # Name extraction
        name = (
            record.get("CardName")
            or f"{record.get('FirstName', '')} {record.get('LastName', '')}".strip()
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
