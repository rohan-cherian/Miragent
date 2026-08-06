"""
scout/connectors/oracle_erp.py — Production Oracle ERP Cloud / Fusion Connector (Sprint 32)

Oracle ERP Cloud (Oracle Fusion) is the dominant enterprise ERP for PE-backed
companies in the $150M–$1B ARR range, especially in financial services, healthcare,
and professional services. It competes with SAP S/4HANA and Workday Financials.

Oracle ERP Cloud covers:
  - Financials (GL, AP, AR, Fixed Assets)
  - Procurement (Purchase Orders, Supplier Management)
  - Project Portfolio Management
  - Supply Chain

Authentication:
  Oracle ERP Cloud uses OAuth 2.0 with JWT Bearer (three-legged) or
  Basic Auth with service account for on-prem/hybrid deployments.
  Most PE portfolio companies on ERP Cloud use Basic Auth with a dedicated
  integration user (simpler to configure than JWT in a service context).

  For Oracle ERP Cloud:
    Base URL: https://{instance}.fa.us2.oraclecloud.com
    Auth: Basic base64("{username}:{password}") or OAuth 2.0 Bearer

API structure (Oracle REST Data Services — ORDS):
  - /fscmRestApi/resources/11.13.18.05/suppliers          → supplier master
  - /fscmRestApi/resources/11.13.18.05/purchaseOrders     → PO data
  - /fscmRestApi/resources/11.13.18.05/invoices           → AP invoices
  - /fscmRestApi/resources/11.13.18.05/generalLedgerJournalEntries → GL
  - /hcmRestApi/resources/11.13.18.05/workers            → HR workers

Pagination:
  Oracle ORDS uses limit/offset with a `hasMore` boolean and `offset` counter.
  Response: { "items": [...], "hasMore": true/false, "count": N, "offset": N }

Rate limits:
  Oracle Cloud enforces 1000 requests/hour per service account by default.
  We use 0.25/sec (15/min) to stay well within limits.

Entity types:
  - supplier        → vendor/supplier master data
  - purchase_order  → procurement POs
  - invoice         → AP invoices
  - worker          → HR employee records (via HCM REST API)
  - gl_journal      → General Ledger journal entries
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

_FSCM_API = "/fscmRestApi/resources/11.13.18.05"
_HCM_API = "/hcmRestApi/resources/11.13.18.05"
_PAGE_SIZE = 500  # Oracle supports up to 500 per page


class OracleERPConnector(ConnectorBase):
    """
    Production Oracle ERP Cloud connector.

    Supports Basic Auth and OAuth 2.0 Bearer for Oracle Fusion Cloud.
    Covers financials, procurement, and HCM modules via Oracle REST APIs.

    Credentials (auth_data keys — Basic Auth):
        auth_mode  — "basic" (default) or "oauth2"
        instance   — Oracle Cloud instance name, e.g. "acme-prod"
        username   — Oracle service account username
        password   — Oracle service account password

    Credentials (auth_data keys — OAuth2):
        auth_mode    — "oauth2"
        instance     — Oracle Cloud instance name
        client_id    — OAuth client ID
        client_secret — OAuth client secret
        token_url    — Oracle OAuth token endpoint
    """

    CONNECTOR_ID = "oracle_erp"
    DISPLAY_NAME = "Oracle ERP Cloud / Fusion (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 0.25  # 15/min — conservative for Oracle's 1000/hr limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._auth_mode: str = "basic"
        self._auth_header: str = ""
        self._base_url: str = ""
        self._token_expires_at: float = 0.0

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """Route to Basic Auth or OAuth2 based on auth_mode."""
        auth = self.credentials.auth_data
        self._auth_mode = auth.get("auth_mode", "basic")
        instance = auth.get("instance", "")

        if not instance:
            logger.error("OracleERPConnector: missing required auth_data key 'instance'")
            return False

        self._base_url = f"https://{instance}.fa.us2.oraclecloud.com"

        if self._auth_mode == "basic":
            return self._authenticate_basic(auth)
        elif self._auth_mode == "oauth2":
            return self._authenticate_oauth2(auth)
        else:
            logger.error(
                "OracleERPConnector: unknown auth_mode '%s'. Use 'basic' or 'oauth2'.",
                self._auth_mode,
            )
            return False

    def _authenticate_basic(self, auth: dict) -> bool:
        username = auth.get("username", "")
        password = auth.get("password", "")
        if not username or not password:
            logger.error(
                "OracleERPConnector Basic: missing 'username' or 'password'"
            )
            return False

        raw = f"{username}:{password}"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()

        try:
            # Validate by fetching 1 supplier
            resp = self._http_client.get(
                f"{self._base_url}{_FSCM_API}/suppliers",
                params={"limit": 1, "offset": 0},
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info(
                "OracleERPConnector Basic authenticated: instance=%s tenant=%s",
                auth.get("instance"), self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "OracleERPConnector Basic auth HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("OracleERPConnector Basic auth error: %s", exc)
            return False

    def _authenticate_oauth2(self, auth: dict) -> bool:
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        token_url = auth.get("token_url", "")

        if not all([client_id, client_secret, token_url]):
            logger.error(
                "OracleERPConnector OAuth2: missing client_id, client_secret, or token_url"
            )
            return False

        try:
            resp = self._http_client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "openid",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("OracleERPConnector OAuth2: no access_token in response")
                return False
            self._auth_header = f"Bearer {token}"
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            logger.info(
                "OracleERPConnector OAuth2 authenticated: tenant=%s", self.tenant_id
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "OracleERPConnector OAuth2 token HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("OracleERPConnector OAuth2 auth error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        if self._auth_mode == "oauth2" and time.time() > self._token_expires_at - 300:
            logger.debug("OracleERPConnector: refreshing OAuth2 token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="supplier",
                display_name="Oracle Suppliers",
                supports_incremental=True,
                fields=[
                    "SupplierId", "SupplierName", "SupplierNumber",
                    "TaxpayerIdNumber", "TaxRegistrationNumber",
                    "PaymentTerms", "CurrencyCode",
                    "AddressLine1", "City", "Country",
                    "PrimaryContactFirstName", "PrimaryContactLastName",
                    "PrimaryContactEmail", "ActiveFlag",
                    "CreationDate", "LastUpdateDate",
                ],
            ),
            EntitySchema(
                entity_type="purchase_order",
                display_name="Oracle Purchase Orders",
                supports_incremental=True,
                fields=[
                    "OrderNumber", "OrderDate", "Status",
                    "SupplierName", "SupplierId",
                    "BuyerName", "BuyerEmail",
                    "Currency", "TotalAmount",
                    "Description", "RequisitionNumber",
                    "CreationDate", "LastUpdateDate",
                ],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="Oracle AP Invoices",
                supports_incremental=True,
                fields=[
                    "InvoiceId", "InvoiceNumber", "InvoiceDate",
                    "SupplierName", "SupplierId",
                    "InvoiceAmount", "AmountPaid", "AmountRemaining",
                    "Currency", "PaymentStatus", "InvoiceStatus",
                    "DueDate", "CreationDate", "LastUpdateDate",
                ],
            ),
            EntitySchema(
                entity_type="worker",
                display_name="Oracle HCM Workers",
                supports_incremental=True,
                fields=[
                    "PersonId", "PersonNumber", "DisplayName",
                    "FirstName", "LastName", "MiddleNames",
                    "DateOfBirth", "NationalIdentifier",
                    "WorkerType", "PrimaryWorkEmail",
                    "JobName", "DepartmentName", "LocationName",
                    "ManagerPersonNumber", "EffectiveStartDate",
                    "ActualTerminationDate", "WorkerStatus",
                    "CreationDate", "LastUpdateDate",
                ],
            ),
            EntitySchema(
                entity_type="gl_journal",
                display_name="Oracle GL Journal Entries",
                supports_incremental=True,
                fields=[
                    "JournalId", "JournalName", "EnteredDate",
                    "AccountedDate", "LedgerName", "Currency",
                    "Status", "Category", "Source",
                    "EnteredDr", "EnteredCr", "AccountedDr", "AccountedCr",
                    "CreationDate",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """Full extraction via Oracle ORDS with limit/offset pagination."""
        config = self._entity_config(entity_type)
        yield from self._paginate_oracle(
            api_path=config["path"],
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
        Incremental extraction using Oracle's LastUpdateDate filter.

        Oracle ORDS supports OData-style $filter queries.
        Format: ?q={"LastUpdateDate":{"$gte":"2026-01-01T00:00:00"}}
        """
        config = self._entity_config(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S")
        date_field = config.get("date_field", "LastUpdateDate")
        oracle_filter = f'{{"{date_field}":{{"$gte":"{since_iso}"}}}}'

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_oracle(
                api_path=config["path"],
                entity_type=entity_type,
                oracle_filter=oracle_filter,
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
                f"{self._base_url}{_FSCM_API}/suppliers",
                params={"limit": 1, "offset": 0},
                headers=self._headers(),
            )
            _ = resp.get("items", [])
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
            "supplier":       {"path": f"{_FSCM_API}/suppliers",
                               "date_field": "LastUpdateDate"},
            "purchase_order": {"path": f"{_FSCM_API}/purchaseOrders",
                               "date_field": "LastUpdateDate"},
            "invoice":        {"path": f"{_FSCM_API}/invoices",
                               "date_field": "LastUpdateDate"},
            "worker":         {"path": f"{_HCM_API}/workers",
                               "date_field": "LastUpdateDate"},
            "gl_journal":     {"path": f"{_FSCM_API}/generalLedgerJournalEntries",
                               "date_field": "CreationDate"},
        }
        if entity_type not in configs:
            raise ValueError(
                f"OracleERPConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_oracle(
        self,
        api_path: str,
        entity_type: str,
        oracle_filter: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Oracle ORDS using limit/offset with hasMore boolean.

        Oracle response structure:
          {
            "items": [...records...],
            "hasMore": true,
            "count": 500,
            "offset": 0,
            "totalResults": 15000,
            "links": [...]
          }
        """
        self._refresh_if_needed()
        offset = 0

        while True:
            params: dict[str, Any] = {"limit": _PAGE_SIZE, "offset": offset}
            if oracle_filter:
                params["q"] = oracle_filter

            try:
                resp = self._get(
                    f"{self._base_url}{api_path}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "OracleERPConnector pagination error (path=%s offset=%d): %s",
                    api_path, offset, exc,
                )
                break

            items = resp.get("items", [])
            for item in items:
                yield self._to_raw_record(entity_type, item)

            has_more = resp.get("hasMore", False)
            if not has_more or not items:
                break
            offset += len(items)

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(
            record.get("SupplierId")
            or record.get("PersonId")
            or record.get("OrderNumber")
            or record.get("InvoiceId")
            or record.get("JournalId")
            or ""
        )
        email = (
            record.get("PrimaryContactEmail")
            or record.get("PrimaryWorkEmail")
            or record.get("email")
        )
        name = (
            record.get("SupplierName")
            or record.get("DisplayName")
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
