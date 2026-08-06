"""
scout/connectors/quickbooks.py — Production QuickBooks Online Connector (Sprint 37)

QuickBooks Online (QBO) is the dominant accounting platform for SMB companies
($1M–$50M ARR) in PE portfolios — primarily in services, agencies, and consumer
businesses. Complements the larger ERP connectors (NetSuite, SAP, Oracle) for
the smaller end of the portfolio.

For Miragent:
  - P&L and balance sheet signals (financial health)
  - Vendor/supplier spend analysis
  - Accounts receivable aging (collection risk)
  - Accounts payable status (cash flow signals)
  - Employee/contractor list (workforce intelligence)

Authentication:
  QuickBooks Online uses OAuth 2.0 with a refresh token (authorization code flow).
  The refresh token must be pre-obtained and stored; this connector exchanges it
  for access tokens.
  Token endpoint: https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer

API structure:
  Base: https://quickbooks.api.intuit.com/v3/company/{realmId}
  Queries use QBO's SQL-like query language via the /query endpoint.

Pagination:
  QBO uses startPosition + maxResults.
  Response: { "QueryResponse": { "Vendor": [...], "startPosition": 1, "maxResults": 100, "totalCount": N } }

Rate limits:
  QBO: 500 requests/minute per app/company.
  We use 5/sec (300/min) as a safe default.

Entity types:
  - vendor    → QBO vendor records
  - customer  → QBO customer records
  - bill      → QBO AP bills
  - invoice   → QBO AR invoices
  - employee  → QBO employee list
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

_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_API_BASE = "https://quickbooks.api.intuit.com/v3/company"
_PAGE_SIZE = 1000  # QBO max per query


class QuickBooksConnector(ConnectorBase):
    """
    Production QuickBooks Online connector.

    Credentials (auth_data keys):
        client_id      — QBO OAuth2 client ID
        client_secret  — QBO OAuth2 client secret
        refresh_token  — Pre-issued refresh token (long-lived)
        realm_id       — QBO company Realm ID (numeric)
    """

    CONNECTOR_ID = "quickbooks"
    DISPLAY_NAME = "QuickBooks Online (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._realm_id: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        import base64

        auth = self.credentials.auth_data
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        refresh_token = auth.get("refresh_token", "")
        self._realm_id = auth.get("realm_id", "")

        if not all([client_id, client_secret, refresh_token, self._realm_id]):
            logger.error(
                "QuickBooksConnector: missing 'client_id', 'client_secret', "
                "'refresh_token', or 'realm_id'"
            )
            return False

        # Basic Auth header: base64(client_id:client_secret)
        cred = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        try:
            resp = self._http_client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={
                    "Authorization": f"Basic {cred}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("QuickBooksConnector: no access_token in response")
                return False
            self._access_token = token
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            logger.info("QuickBooksConnector authenticated: realm=%s tenant=%s", self._realm_id, self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("QuickBooksConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("QuickBooksConnector auth error: %s", exc)
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
                display_name="QuickBooks Vendors",
                supports_incremental=True,
                fields=[
                    "Id", "DisplayName", "CompanyName", "GivenName", "FamilyName",
                    "PrimaryEmailAddr", "PrimaryPhone", "BillAddr",
                    "TaxIdentifier", "Active", "Balance",
                    "MetaData",
                ],
            ),
            EntitySchema(
                entity_type="customer",
                display_name="QuickBooks Customers",
                supports_incremental=True,
                fields=[
                    "Id", "DisplayName", "CompanyName", "GivenName", "FamilyName",
                    "PrimaryEmailAddr", "PrimaryPhone", "BillAddr",
                    "Active", "Balance", "BalanceWithJobs",
                    "MetaData",
                ],
            ),
            EntitySchema(
                entity_type="bill",
                display_name="QuickBooks Bills (AP)",
                supports_incremental=True,
                fields=[
                    "Id", "VendorRef", "APAccountRef", "TxnDate",
                    "DueDate", "TotalAmt", "Balance",
                    "PaymentType", "MetaData",
                ],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="QuickBooks Invoices (AR)",
                supports_incremental=True,
                fields=[
                    "Id", "CustomerRef", "TxnDate", "DueDate",
                    "TotalAmt", "Balance", "DocNumber",
                    "EmailStatus", "MetaData",
                ],
            ),
            EntitySchema(
                entity_type="employee",
                display_name="QuickBooks Employees",
                supports_incremental=True,
                fields=[
                    "Id", "DisplayName", "GivenName", "FamilyName",
                    "PrimaryEmailAddr", "PrimaryPhone", "BillableTime",
                    "Active", "MetaData",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        qbo_entity = self._entity_qbo_name(entity_type)
        query = f"SELECT * FROM {qbo_entity} MAXRESULTS {_PAGE_SIZE}"
        yield from self._paginate_query(
            base_query=f"SELECT * FROM {qbo_entity}",
            qbo_entity=qbo_entity,
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
        Incremental via QBO query on MetaData.LastUpdatedTime.
        Format: WHERE MetaData.LastUpdatedTime > '2026-01-01T00:00:00-07:00'
        """
        qbo_entity = self._entity_qbo_name(entity_type)
        since_str = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S-07:00")
        base_query = (
            f"SELECT * FROM {qbo_entity} "
            f"WHERE MetaData.LastUpdatedTime > '{since_str}'"
        )

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_query(
                base_query=base_query,
                qbo_entity=qbo_entity,
                entity_type=entity_type,
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
                f"{_API_BASE}/{self._realm_id}/query",
                params={"query": "SELECT * FROM Vendor MAXRESULTS 1"},
                headers=self._headers(),
            )
            _ = resp.get("QueryResponse", {})
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

    def _entity_qbo_name(self, entity_type: str) -> str:
        names = {
            "vendor":   "Vendor",
            "customer": "Customer",
            "bill":     "Bill",
            "invoice":  "Invoice",
            "employee": "Employee",
        }
        if entity_type not in names:
            raise ValueError(
                f"QuickBooksConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(names)}"
            )
        return names[entity_type]

    def _paginate_query(
        self,
        base_query: str,
        qbo_entity: str,
        entity_type: str,
    ) -> Iterator[RawRecord]:
        """
        Paginate QBO query using startPosition + MAXRESULTS.
        Response: { "QueryResponse": { "Vendor": [...], "startPosition": 1, "maxResults": N, "totalCount": N } }
        """
        self._refresh_if_needed()
        start_pos = 1

        while True:
            query = f"{base_query} STARTPOSITION {start_pos} MAXRESULTS {_PAGE_SIZE}"
            try:
                resp = self._get(
                    f"{_API_BASE}/{self._realm_id}/query",
                    params={"query": query},
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("QuickBooksConnector query error (entity=%s): %s", entity_type, exc)
                break

            qr = resp.get("QueryResponse", {})
            records = qr.get(qbo_entity, [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            start_pos += len(records)

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("Id", ""))
        email_obj = record.get("PrimaryEmailAddr", {})
        email = email_obj.get("Address") if isinstance(email_obj, dict) else email_obj
        name = (
            record.get("DisplayName")
            or record.get("CompanyName")
            or f"{record.get('GivenName', '')} {record.get('FamilyName', '')}".strip()
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
