"""
scout/connectors/concur.py — Production SAP Concur Connector (Sprint 37)

SAP Concur is the dominant enterprise travel & expense management platform,
used by larger PE-backed companies ($100M+ ARR) with significant employee
travel budgets. Often paired with SAP S/4HANA or Oracle ERP.

For Miragent:
  - T&E spend visibility by department and employee
  - Policy compliance monitoring (out-of-policy expenses)
  - Vendor spend: which hotels, airlines, car services?
  - Offboarding: flag open expense reports for departed employees

Authentication:
  Concur uses OAuth 2.0 Client Credentials with a company UUID.
  Token endpoint: https://us.api.concursolutions.com/oauth2/v0/token

API structure:
  Base: https://us.api.concursolutions.com
  - /api/v3.0/expense/reports       → expense reports
  - /api/v3.0/expense/entries       → expense line items
  - /api/v3.0/travel/trip/v1.1      → travel itineraries
  - /profile/identity/v4/users      → user profiles

Pagination:
  Concur uses offset + limit with `NextPage` URL in the response.
  Response: { "Items": [...], "NextPage": "https://...", "TotalCount": N }

Rate limits:
  Concur: 1000 requests/minute for standard API access.
  We use 2/sec (120/min) as a conservative default.

Entity types:
  - report   → expense reports (header level)
  - entry    → expense line items
  - user     → Concur user profiles
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

_TOKEN_BASE = "https://us.api.concursolutions.com"
_API_BASE = "https://us.api.concursolutions.com"
_PAGE_SIZE = 100


class ConcurConnector(ConnectorBase):
    """
    Production SAP Concur Travel & Expense connector.

    Credentials (auth_data keys):
        client_id      — Concur OAuth2 client ID
        client_secret  — Concur OAuth2 client secret
        company_uuid   — Concur company UUID (geolocation routing)
        region         — API region: "us" (default), "eu", "cn"
    """

    CONNECTOR_ID = "concur"
    DISPLAY_NAME = "SAP Concur Travel & Expense (Production)"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 2.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._api_base: str = _API_BASE

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        company_uuid = auth.get("company_uuid", "")
        region = auth.get("region", "us")

        if not all([client_id, client_secret, company_uuid]):
            logger.error("ConcurConnector: missing 'client_id', 'client_secret', or 'company_uuid'")
            return False

        token_base = f"https://{region}.api.concursolutions.com"
        self._api_base = token_base

        try:
            resp = self._http_client.post(
                f"{token_base}/oauth2/v0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "company_uuid": company_uuid,
                    "credtype": "authtoken",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("ConcurConnector: no access_token in response")
                return False
            self._access_token = token
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            logger.info("ConcurConnector authenticated: tenant=%s", self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("ConcurConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("ConcurConnector auth error: %s", exc)
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
                entity_type="report",
                display_name="Concur Expense Reports",
                supports_incremental=True,
                fields=[
                    "ID", "Name", "OwnerLoginID", "OwnerName",
                    "Total", "CurrencyCode", "ApprovalStatusCode",
                    "PaymentStatusCode", "SubmitDate", "ApprovalDate",
                    "CreateDate", "LastModifiedDate",
                ],
            ),
            EntitySchema(
                entity_type="entry",
                display_name="Concur Expense Entries",
                supports_incremental=True,
                fields=[
                    "ID", "ReportID", "ExpenseTypeCode", "TransactionDate",
                    "TransactionAmount", "TransactionCurrencyCode",
                    "VendorDescription", "BusinessPurpose",
                    "LastModified",
                ],
            ),
            EntitySchema(
                entity_type="user",
                display_name="Concur Users",
                supports_incremental=False,
                fields=[
                    "ID", "LoginID", "FirstName", "LastName",
                    "EmailAddress", "Active", "CellPhoneNumber",
                    "CountryCode", "CurrencyCode",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        config = self._entity_config(entity_type)
        yield from self._paginate_concur(
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
        config = self._entity_config(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S")
        date_filter = config.get("date_filter", "modifiedafterdate")

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_concur(
                endpoint=config["endpoint"],
                entity_type=entity_type,
                extra_params={date_filter: since_iso},
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
                f"{self._api_base}/api/v3.0/expense/reports",
                params={"limit": 1, "offset": 0},
                headers=self._headers(),
            )
            _ = resp.get("Items", [])
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
        }

    def _entity_config(self, entity_type: str) -> dict[str, str]:
        configs = {
            "report": {
                "endpoint": "/api/v3.0/expense/reports",
                "date_filter": "modifiedafterdate",
            },
            "entry": {
                "endpoint": "/api/v3.0/expense/entries",
                "date_filter": "lastmodified",
            },
            "user": {
                "endpoint": "/api/v3.0/common/users",
                "date_filter": "",
            },
        }
        if entity_type not in configs:
            raise ValueError(
                f"ConcurConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_concur(
        self,
        endpoint: str,
        entity_type: str,
        extra_params: dict | None = None,
    ) -> Iterator[RawRecord]:
        """
        Paginate Concur API using NextPage URL from response.
        Response: { "Items": [...], "NextPage": "url_or_null", "TotalCount": N }
        """
        self._refresh_if_needed()
        url: str | None = f"{self._api_base}{endpoint}"
        params: dict[str, Any] = {"limit": _PAGE_SIZE, "offset": 0}
        if extra_params:
            params.update(extra_params)

        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error("ConcurConnector pagination error (endpoint=%s): %s", endpoint, exc)
                break

            items = resp.get("Items", [])
            for item in items:
                yield self._to_raw_record(entity_type, item)

            url = resp.get("NextPage")
            params = {}  # NextPage URL has params embedded

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("ID", ""))
        email = record.get("EmailAddress") or record.get("OwnerLoginID")
        name = (
            record.get("OwnerName")
            or f"{record.get('FirstName', '')} {record.get('LastName', '')}".strip()
            or record.get("Name")
            or record.get("VendorDescription")
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
