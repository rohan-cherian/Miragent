"""
scout/connectors/dynamics_365.py — Production Microsoft Dynamics 365 Connector (Sprint 32)

Microsoft Dynamics 365 is the Microsoft-native ERP + CRM suite. In PE mid-market,
it appears in two major configurations:

  Dynamics 365 Finance & Operations (F&O) — ERP module
    Covers: Accounts Payable, Accounts Receivable, General Ledger, Procurement,
            Inventory, Project Accounting
    API: OData v4 over HTTPS with Azure AD Bearer token

  Dynamics 365 Business Central — SMB ERP (replaces Navision/NAV)
    Covers: Finance, Sales, Purchasing, Inventory
    API: OData v4 with Basic Auth or Azure AD

  Dynamics 365 Sales (CRM) — covered separately in sprint 33
    This connector handles the ERP/Finance modules only.

Authentication:
  Both F&O and Business Central use Azure AD OAuth 2.0 Client Credentials.
  The resource/scope differs:
    F&O:              https://{instance}.operations.dynamics.com/.default
    Business Central: https://api.businesscentral.dynamics.com/.default

API structure (F&O):
  Base: https://{instance}.operations.dynamics.com
  - /data/Vendors              → vendor master
  - /data/Customers            → customer master
  - /data/PurchaseOrderHeaders → purchase orders
  - /data/VendorInvoiceHeaders → AP invoices
  - /data/Workers              → HR worker list

API structure (Business Central):
  Base: https://api.businesscentral.dynamics.com/v2.0/{tenant}/production/api/v2.0
  - /vendors
  - /customers
  - /purchaseOrders
  - /purchaseInvoices

Pagination:
  Both use OData @odata.nextLink for pagination (same pattern as Azure AD).

Rate limits:
  Dynamics F&O: 6000 requests/day per app by default; 12/min burst.
  Business Central: 300 requests/minute.
  We use 4/sec (240/min) as a safe rate for either variant.

Entity types:
  - vendor         → supplier/vendor master data
  - customer       → customer master data
  - purchase_order → procurement PO records
  - invoice        → AP invoice records
  - worker         → employee records (F&O only)
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

_TOKEN_BASE = "https://login.microsoftonline.com"
_PAGE_SIZE = 1000  # OData max for Dynamics


class Dynamics365Connector(ConnectorBase):
    """
    Production Microsoft Dynamics 365 Finance & Operations / Business Central connector.

    Handles both F&O (enterprise ERP) and Business Central (SMB ERP) via
    the same connector architecture. auth_mode selects the variant.

    Credentials (auth_data keys):
        auth_mode      — "fo" (Finance & Operations) or "bc" (Business Central)
        tenant_id      — Azure AD tenant ID (GUID)
        client_id      — Service principal / app registration client ID
        client_secret  — Service principal client secret
        instance       — Dynamics instance name
                         F&O: e.g. "acme-prod" (→ acme-prod.operations.dynamics.com)
                         BC:  e.g. "acme-tenant-guid" (Azure AD tenant for BC API)
        company_id     — (BC only) Business Central company ID
    """

    CONNECTOR_ID = "dynamics_365"
    DISPLAY_NAME = "Microsoft Dynamics 365 Finance (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 4.0  # 240/min — safe for both F&O and BC limits

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._auth_mode: str = "fo"
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._base_url: str = ""
        self._aad_tenant_id: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Authenticate against Microsoft Identity Platform using Client Credentials.
        Scope differs between F&O and Business Central.
        """
        auth = self.credentials.auth_data
        self._auth_mode = auth.get("auth_mode", "fo")
        self._aad_tenant_id = auth.get("tenant_id", "")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        instance = auth.get("instance", "")

        if not all([self._aad_tenant_id, client_id, client_secret, instance]):
            logger.error(
                "Dynamics365Connector: missing required auth_data keys "
                "(tenant_id, client_id, client_secret, instance)"
            )
            return False

        # Set base URL and scope based on auth_mode
        if self._auth_mode == "fo":
            self._base_url = f"https://{instance}.operations.dynamics.com"
            scope = f"https://{instance}.operations.dynamics.com/.default"
        elif self._auth_mode == "bc":
            company_id = auth.get("company_id", "")
            self._base_url = (
                f"https://api.businesscentral.dynamics.com/v2.0"
                f"/{instance}/production/api/v2.0"
            )
            if company_id:
                self._base_url += f"/companies({company_id})"
            scope = "https://api.businesscentral.dynamics.com/.default"
        else:
            logger.error(
                "Dynamics365Connector: unknown auth_mode '%s'. Use 'fo' or 'bc'.",
                self._auth_mode,
            )
            return False

        try:
            resp = self._http_client.post(
                f"{_TOKEN_BASE}/{self._aad_tenant_id}/oauth2/v2.0/token",
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
            self._access_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

            if not self._access_token:
                logger.error(
                    "Dynamics365Connector: no access_token in response. "
                    "tenant=%s", self.tenant_id
                )
                return False

            logger.info(
                "Dynamics365Connector authenticated: mode=%s instance=%s tenant=%s",
                self._auth_mode, instance, self.tenant_id,
            )
            return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Dynamics365Connector.authenticate HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("Dynamics365Connector.authenticate error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        if time.time() > self._token_expires_at - 300:
            logger.debug("Dynamics365Connector: refreshing access token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Dynamics 365 Vendors",
                supports_incremental=True,
                fields=[
                    # F&O fields
                    "VendorAccountNumber", "VendorGroupId", "OrganizationName",
                    "PrimaryContactEmail", "CurrencyCode", "PaymentTerms",
                    "IsSuspended", "IsOneTimeVendor",
                    # BC fields (alternate names)
                    "number", "displayName", "email", "blocked", "currencyCode",
                    "paymentTermsId", "lastModifiedDateTime",
                ],
            ),
            EntitySchema(
                entity_type="customer",
                display_name="Dynamics 365 Customers",
                supports_incremental=True,
                fields=[
                    "CustomerAccountNumber", "CustomerGroupId", "OrganizationName",
                    "PrimaryContactEmail", "CurrencyCode", "CreditLimit",
                    "CustomerClassificationId",
                    # BC fields
                    "number", "displayName", "email", "blocked",
                    "creditLimit", "lastModifiedDateTime",
                ],
            ),
            EntitySchema(
                entity_type="purchase_order",
                display_name="Dynamics 365 Purchase Orders",
                supports_incremental=True,
                fields=[
                    "PurchaseOrderNumber", "VendorAccountNumber", "PurchaseOrderStatus",
                    "OrderDate", "TotalInvoiceAmount", "CurrencyCode",
                    "RequestedDeliveryDate", "PurchasingUnit",
                    # BC
                    "number", "vendorNumber", "status", "orderDate",
                    "totalAmountIncludingTax", "lastModifiedDateTime",
                ],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="Dynamics 365 Vendor Invoices",
                supports_incremental=True,
                fields=[
                    "InvoiceNumber", "VendorAccountNumber", "InvoiceDate",
                    "DueDate", "InvoiceAmount", "PaymentStatus",
                    "CurrencyCode", "PurchaseOrderNumber",
                    # BC
                    "number", "vendorNumber", "invoiceDate", "dueDate",
                    "totalAmountIncludingTax", "status", "lastModifiedDateTime",
                ],
            ),
            EntitySchema(
                entity_type="worker",
                display_name="Dynamics 365 Workers (F&O HCM)",
                supports_incremental=True,
                fields=[
                    "PersonnelNumber", "WorkerType",
                    "PrimaryEmailAddress", "EmploymentStartDate",
                    "EmploymentEndDate", "WorkerStatus",
                    "DepartmentNumber", "JobId", "PositionId",
                    "LastModifiedDateTime",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """Full extraction via OData with @odata.nextLink pagination."""
        config = self._entity_config(entity_type)
        yield from self._paginate_odata(
            endpoint=config["endpoint"],
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
        Incremental via OData $filter on modifiedDateTime / lastModifiedDateTime.

        F&O: $filter=modifiedDateTime ge 2026-01-01T00:00:00Z
        BC:  $filter=lastModifiedDateTime ge 2026-01-01T00:00:00Z
        """
        config = self._entity_config(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        date_field = "lastModifiedDateTime" if self._auth_mode == "bc" else "modifiedDateTime"
        odata_filter = f"{date_field} ge {since_iso}"

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_odata(
                endpoint=config["endpoint"],
                entity_type=entity_type,
                odata_filter=odata_filter,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": since_iso, "mode": self._auth_mode},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            self._refresh_if_needed()
            config = self._entity_config("vendor")
            resp = self._get(
                f"{self._base_url}{config['endpoint']}",
                params={"$top": 1},
                headers=self._headers(),
            )
            _ = resp.get("value", [])
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
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        }

    def _entity_config(self, entity_type: str) -> dict[str, str]:
        """Return API endpoint for entity type, varying by auth_mode."""
        if self._auth_mode == "bc":
            configs = {
                "vendor":         {"endpoint": "/vendors"},
                "customer":       {"endpoint": "/customers"},
                "purchase_order": {"endpoint": "/purchaseOrders"},
                "invoice":        {"endpoint": "/purchaseInvoices"},
                "worker":         {"endpoint": "/employees"},
            }
        else:  # fo (Finance & Operations)
            configs = {
                "vendor":         {"endpoint": "/data/Vendors"},
                "customer":       {"endpoint": "/data/Customers"},
                "purchase_order": {"endpoint": "/data/PurchaseOrderHeaders"},
                "invoice":        {"endpoint": "/data/VendorInvoiceHeaders"},
                "worker":         {"endpoint": "/data/Workers"},
            }

        if entity_type not in configs:
            raise ValueError(
                f"Dynamics365Connector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_odata(
        self,
        endpoint: str,
        entity_type: str,
        odata_filter: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Dynamics 365 OData results via @odata.nextLink.

        Response structure:
          { "value": [...records...], "@odata.nextLink": "..." }
        """
        self._refresh_if_needed()
        url: str | None = f"{self._base_url}{endpoint}"
        params: dict[str, Any] = {"$top": _PAGE_SIZE}
        if odata_filter:
            params["$filter"] = odata_filter

        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error(
                    "Dynamics365Connector pagination error (endpoint=%s): %s",
                    endpoint, exc,
                )
                break

            records = resp.get("value", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            url = resp.get("@odata.nextLink")
            params = {}  # nextLink has params embedded

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        """Convert a Dynamics 365 record to RawRecord."""
        source_id = str(
            record.get("VendorAccountNumber")
            or record.get("CustomerAccountNumber")
            or record.get("PurchaseOrderNumber")
            or record.get("InvoiceNumber")
            or record.get("PersonnelNumber")
            or record.get("number")
            or record.get("id")
            or ""
        )
        email = (
            record.get("PrimaryContactEmail")
            or record.get("PrimaryEmailAddress")
            or record.get("email")
        )
        name = (
            record.get("OrganizationName")
            or record.get("displayName")
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
