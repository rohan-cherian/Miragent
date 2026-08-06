"""
scout/connectors/dynamics_finance.py — Production Microsoft Dynamics 365 Finance Connector (Sprint 38)

Microsoft Dynamics 365 Finance & Operations (F&O) is the enterprise ERP for
large PE-backed companies ($100M+ ARR). It's the successor to AX (Axapta) and
sits above Dynamics 365 Business Central (for smaller companies).

For Miragent:
  - Vendor/supplier spend analysis (AP concentration risk)
  - Worker/employee directory (workforce intelligence)
  - General ledger signals (financial health, EBITDA proxies)

Authentication:
  Dynamics 365 F&O uses Azure Active Directory (AAD) OAuth 2.0 client credentials.
  The app must have the Dynamics 365 Finance API permission granted by an admin.

  Token endpoint: https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
  Scope:          {environment_url}/.default

API structure:
  Base: https://{environment}.operations.dynamics.com/data/
  - /Vendors             → vendor records (VendTable)
  - /HcmWorkers          → worker/employee records
  - /GeneralJournalEntries → GL entries

  OData standard: $top, $skiptoken (server-side cursor for large datasets).

Pagination:
  Dynamics F&O uses @odata.nextLink (server-side cursor) for pagination.
  Never use $skip — it's not supported on large datasets.

Rate limits:
  Dynamics 365 F&O: no published hard rate limit per operation type.
  In practice, concurrent API sessions are limited.
  We use 3/sec as a conservative default.

Entity types:
  - vendor  → Dynamics vendor records
  - worker  → Dynamics worker/employee records
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

_PAGE_SIZE = 1000  # Dynamics F&O supports up to 10,000 but 1,000 is safer


class DynamicsFinanceConnector(ConnectorBase):
    """
    Production Microsoft Dynamics 365 Finance & Operations connector.

    Uses Azure AD client credentials OAuth 2.0.

    Credentials (auth_data keys):
        tenant_id        — Azure AD tenant ID (GUID)
        client_id        — Azure AD application (client) ID
        client_secret    — Azure AD client secret
        environment_url  — Dynamics F&O environment URL
                           e.g. "https://acme.operations.dynamics.com"
    """

    CONNECTOR_ID = "dynamics_finance"
    DISPLAY_NAME = "Microsoft Dynamics 365 Finance (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 3.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._environment_url: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """Obtain an Azure AD access token via client credentials flow."""
        auth = self.credentials.auth_data
        aad_tenant_id = auth.get("tenant_id", "")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        environment_url = auth.get("environment_url", "").rstrip("/")

        if not all([aad_tenant_id, client_id, client_secret, environment_url]):
            logger.error(
                "DynamicsFinanceConnector: missing 'tenant_id', 'client_id', "
                "'client_secret', or 'environment_url'"
            )
            return False

        self._environment_url = environment_url
        token_url = (
            f"https://login.microsoftonline.com/{aad_tenant_id}/oauth2/v2.0/token"
        )
        scope = f"{environment_url}/.default"

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
                logger.error("DynamicsFinanceConnector: no access_token in response")
                return False
            self._access_token = token
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            logger.info(
                "DynamicsFinanceConnector authenticated: env=%s tenant=%s",
                environment_url, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "DynamicsFinanceConnector auth HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("DynamicsFinanceConnector auth error: %s", exc)
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
                entity_type="vendor",
                display_name="Dynamics 365 Finance Vendors",
                supports_incremental=True,
                fields=[
                    "AccountNum", "VendorGroupId", "Name",
                    "CurrencyCode", "PaymentTermId", "InvoiceAccount",
                    "TaxGroup", "TaxRegistrationNumber",
                    "ModifiedDateTime",
                ],
            ),
            EntitySchema(
                entity_type="worker",
                display_name="Dynamics 365 Finance Workers",
                supports_incremental=True,
                fields=[
                    "PersonnelNumber", "WorkerType",
                    "PrimaryEmailAddress",
                    "OfficeLocation",
                    "ModifiedDateTime",
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
        Incremental via OData $filter on ModifiedDateTime.
        Format: ModifiedDateTime gt 2026-01-01T00:00:00Z
        """
        endpoint = self._entity_endpoint(entity_type)
        since_str = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        odata_filter = f"ModifiedDateTime gt {since_str}"

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
            self._refresh_if_needed()
            resp = self._get(
                f"{self._environment_url}/data/Vendors",
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
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        }

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "vendor": "/data/Vendors",
            "worker": "/data/HcmWorkers",
        }
        if entity_type not in endpoints:
            raise ValueError(
                f"DynamicsFinanceConnector does not support entity_type='{entity_type}'. "
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
        Paginate Dynamics 365 F&O OData using @odata.nextLink.
        Response: {"value": [...], "@odata.nextLink": "..."}

        Dynamics does NOT support $skip — we must use @odata.nextLink.
        """
        self._refresh_if_needed()
        url = f"{self._environment_url}{endpoint}"
        params: dict[str, Any] = {"$top": _PAGE_SIZE}
        if extra_filter:
            params["$filter"] = extra_filter

        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error(
                    "DynamicsFinanceConnector pagination error (endpoint=%s): %s",
                    endpoint, exc,
                )
                break

            records = resp.get("value", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            # Use @odata.nextLink for next page; clear params (URL is complete)
            url = resp.get("@odata.nextLink", "")
            params = {}  # nextLink already contains all query params

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        if entity_type == "vendor":
            source_id = str(record.get("AccountNum", ""))
            name = record.get("Name") or None
            email = None
        else:  # worker
            source_id = str(record.get("PersonnelNumber", ""))
            name = (
                record.get("PrimaryWorkerName")
                or record.get("PersonnelNumber")
                or None
            )
            email = record.get("PrimaryEmailAddress") or None

        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.tenant_id,
            payload=record,
            email_hint=email,
            name_hint=name,
        )
