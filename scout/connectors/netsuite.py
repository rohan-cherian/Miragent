"""
scout/connectors/netsuite.py — Production NetSuite ERP Connector (Sprint 29)

NetSuite is the #1 ERP in PE-backed mid-market companies and is one of
Miragent's three primary data sources. This connector uses NetSuite's
REST API (SuiteTalk REST) with Token-Based Authentication (TBA), which
is the recommended integration method for service integrations.

Authentication:
  NetSuite TBA uses OAuth 1.0a with four credentials:
  - consumer_key + consumer_secret (the integration record)
  - token_id + token_secret (the user access token)
  These are combined to sign each request with an HMAC-SHA256 signature.

  Alternative: OAuth 2.0 Client Credentials (newer, preferred for new setups).
  We support both via a flag in auth_data.

API structure:
  Base URL: https://{account_id}.suitetalk.api.netsuite.com/services/rest/
  - record/v1/          → CRUD on individual record types
  - query/v1/suiteql    → SQL-like queries across multiple record types

  SuiteQL is preferred for bulk extraction — it supports JOINs, filters,
  and pagination and is far more efficient than the record API for reporting.

Entity types:
  - vendor         → vendor master (for Vendor Benchmark Worker)
  - customer       → customer accounts (for cross-referencing with SFDC)
  - employee       → NetSuite employee records
  - purchase_order → PO records (for approval workflow)
  - invoice        → AR invoices (for collections worker)
  - contract       → custom contract records (if NetSuite Contracts module)

Rate limits:
  NetSuite enforces concurrency limits (not per-second limits):
  - Sandbox: 5 concurrent requests
  - Production: 10–50 depending on license tier
  We use 5.0/sec as a conservative limit that respects concurrency.
"""

import hashlib
import hmac
import logging
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode

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

_PAGE_SIZE = 1000  # SuiteQL supports up to 1000 rows per page


class NetSuiteConnector(ConnectorBase):
    """
    Production NetSuite ERP connector using SuiteTalk REST + SuiteQL.

    Uses Token-Based Authentication (OAuth 1.0a) or OAuth 2.0 Client
    Credentials depending on auth_data configuration.

    Credentials (auth_data keys for TBA):
        account_id       — NetSuite account ID (e.g. "1234567")
        consumer_key     — Integration consumer key
        consumer_secret  — Integration consumer secret
        token_id         — User access token ID
        token_secret     — User access token secret

    Credentials (auth_data keys for OAuth 2.0):
        account_id       — NetSuite account ID
        client_id        — OAuth 2.0 client ID
        client_secret    — OAuth 2.0 client secret
        auth_mode        — "oauth2" (default: "tba")
    """

    CONNECTOR_ID = "netsuite"
    DISPLAY_NAME = "NetSuite ERP (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    # SuiteQL queries per entity type
    _SUITEQL: dict[str, str] = {
        "vendor": """
            SELECT v.id, v.entityid, v.companyname, v.email,
                   v.phone, v.currency, v.terms, v.creditlimit,
                   v.isinactive, v.lastmodifieddate,
                   v.defaulttaxreg, v.category
            FROM vendor v
            WHERE v.isinactive = 'F'
        """,
        "customer": """
            SELECT c.id, c.entityid, c.companyname, c.email,
                   c.phone, c.currency, c.salesrep,
                   c.creditlimit, c.overduebalance,
                   c.isinactive, c.lastmodifieddate
            FROM customer c
            WHERE c.isinactive = 'F'
        """,
        "employee": """
            SELECT e.id, e.entityid, e.firstname, e.lastname,
                   e.email, e.phone, e.department,
                   e.title, e.supervisor,
                   e.hiredate, e.terminationdate,
                   e.employeestatus, e.isinactive,
                   e.lastmodifieddate
            FROM employee e
        """,
        "purchase_order": """
            SELECT t.id, t.tranid, t.entity AS vendorid,
                   t.trandate, t.duedate, t.amount,
                   t.status, t.memo, t.approvalstatus,
                   t.lastmodifieddate
            FROM transaction t
            WHERE t.type = 'PurchOrd'
        """,
        "invoice": """
            SELECT t.id, t.tranid, t.entity AS customerid,
                   t.trandate, t.duedate, t.amount,
                   t.amountremaining, t.status, t.memo,
                   t.lastmodifieddate
            FROM transaction t
            WHERE t.type = 'CustInvc'
        """,
    }

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._account_id: str = ""
        self._consumer_key: str = ""
        self._consumer_secret: str = ""
        self._token_id: str = ""
        self._token_secret: str = ""
        self._auth_mode: str = "tba"
        self._oauth2_token: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Validate credentials by executing a minimal SuiteQL query.

        For TBA: signs the request using HMAC-SHA256 and verifies a 200 response.
        For OAuth2: obtains a Bearer token from the NetSuite token endpoint.
        """
        auth = self.credentials.auth_data
        account_id = auth.get("account_id", "")
        if not account_id:
            logger.error("NetSuiteConnector: missing 'account_id' in auth_data")
            return False

        self._account_id = account_id.lower().replace("-", "_")
        self._auth_mode = auth.get("auth_mode", "tba")

        if self._auth_mode == "oauth2":
            return self._authenticate_oauth2(auth)
        else:
            return self._authenticate_tba(auth)

    def _authenticate_tba(self, auth: dict) -> bool:
        """OAuth 1.0a TBA authentication."""
        consumer_key = auth.get("consumer_key", "")
        consumer_secret = auth.get("consumer_secret", "")
        token_id = auth.get("token_id", "")
        token_secret = auth.get("token_secret", "")

        if not all([consumer_key, consumer_secret, token_id, token_secret]):
            logger.error(
                "NetSuiteConnector TBA: missing keys "
                "(consumer_key, consumer_secret, token_id, token_secret)"
            )
            return False

        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        self._token_id = token_id
        self._token_secret = token_secret

        # Validate with a minimal SuiteQL ping
        try:
            url = self._suiteql_url()
            result = self._suiteql_page(
                query="SELECT id FROM employee WHERE rownum <= 1",
                offset=0,
            )
            logger.info(
                "NetSuiteConnector TBA authenticated: account=%s tenant=%s",
                self._account_id, self.tenant_id,
            )
            return True
        except Exception as exc:
            logger.error("NetSuiteConnector TBA auth failed: %s", exc)
            return False

    def _authenticate_oauth2(self, auth: dict) -> bool:
        """OAuth 2.0 Client Credentials authentication."""
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        if not client_id or not client_secret:
            logger.error(
                "NetSuiteConnector OAuth2: missing client_id or client_secret"
            )
            return False

        token_url = (
            f"https://{self._account_id}.suitetalk.api.netsuite.com"
            f"/services/rest/auth/oauth2/v1/token"
        )
        try:
            resp = self._http_client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            resp.raise_for_status()
            self._oauth2_token = resp.json().get("access_token", "")
            if not self._oauth2_token:
                logger.error("NetSuiteConnector OAuth2: empty access_token")
                return False
            logger.info(
                "NetSuiteConnector OAuth2 authenticated: account=%s tenant=%s",
                self._account_id, self.tenant_id,
            )
            return True
        except Exception as exc:
            logger.error("NetSuiteConnector OAuth2 auth failed: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="NetSuite Vendors",
                supports_incremental=True,
                fields=["id", "entityid", "companyname", "email", "currency",
                        "terms", "creditlimit", "isinactive", "lastmodifieddate"],
            ),
            EntitySchema(
                entity_type="customer",
                display_name="NetSuite Customers",
                supports_incremental=True,
                fields=["id", "entityid", "companyname", "email", "currency",
                        "salesrep", "creditlimit", "overduebalance", "lastmodifieddate"],
            ),
            EntitySchema(
                entity_type="employee",
                display_name="NetSuite Employees",
                supports_incremental=True,
                fields=["id", "firstname", "lastname", "email", "title",
                        "department", "hiredate", "terminationdate",
                        "employeestatus", "lastmodifieddate"],
            ),
            EntitySchema(
                entity_type="purchase_order",
                display_name="NetSuite Purchase Orders",
                supports_incremental=True,
                fields=["id", "tranid", "vendorid", "trandate", "duedate",
                        "amount", "status", "approvalstatus", "lastmodifieddate"],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="NetSuite AR Invoices",
                supports_incremental=True,
                fields=["id", "tranid", "customerid", "trandate", "duedate",
                        "amount", "amountremaining", "status", "lastmodifieddate"],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in self._SUITEQL:
            raise ValueError(
                f"NetSuiteConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(self._SUITEQL)}"
            )
        yield from self._paginate_suiteql(
            query=self._SUITEQL[entity_type],
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
        if entity_type not in self._SUITEQL:
            raise ValueError(
                f"NetSuiteConnector: unsupported entity_type '{entity_type}'"
            )

        since_str = cursor.last_extracted_at.strftime("%Y-%m-%d")
        base_query = self._SUITEQL[entity_type].strip()

        # Add WHERE or AND for the lastmodifieddate filter
        if "WHERE" in base_query.upper():
            query = f"{base_query} AND lastmodifieddate >= '{since_str}'"
        else:
            query = f"{base_query} WHERE lastmodifieddate >= '{since_str}'"

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_suiteql(
                query=query,
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
            self._suiteql_page(
                query="SELECT id FROM employee WHERE rownum <= 1",
                offset=0,
            )
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

    def _suiteql_url(self) -> str:
        return (
            f"https://{self._account_id}.suitetalk.api.netsuite.com"
            f"/services/rest/query/v1/suiteql"
        )

    def _paginate_suiteql(
        self,
        query: str,
        entity_type: str,
    ) -> Iterator[RawRecord]:
        """Paginate through SuiteQL results using offset pagination."""
        offset = 0
        while True:
            page_data = self._suiteql_page(query=query, offset=offset)
            items = page_data.get("items", [])
            total = page_data.get("totalResults", 0)
            has_more = page_data.get("hasMore", False)

            for record in items:
                source_id = str(
                    record.get("id") or record.get("tranid") or ""
                )
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=record,
                    email_hint=record.get("email"),
                    name_hint=(
                        record.get("companyname")
                        or f"{record.get('firstname', '')} {record.get('lastname', '')}".strip()
                        or record.get("tranid")
                    ) or None,
                )

            offset += len(items)
            if not has_more or not items:
                break

    def _suiteql_page(self, query: str, offset: int) -> dict[str, Any]:
        """Execute a single SuiteQL page request and return the JSON response."""
        url = self._suiteql_url()
        body = {
            "q": query.strip(),
            "limit": _PAGE_SIZE,
            "offset": offset,
        }
        headers = self._auth_headers(method="POST", url=url)
        headers["Prefer"] = "transient"

        resp = self._http_client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def _auth_headers(self, method: str, url: str) -> dict[str, str]:
        """Build auth headers for TBA (OAuth 1.0a) or OAuth 2.0."""
        if self._auth_mode == "oauth2":
            return {
                "Authorization": f"Bearer {self._oauth2_token}",
                "Content-Type": "application/json",
            }
        return self._tba_headers(method=method, url=url)

    def _tba_headers(self, method: str, url: str) -> dict[str, str]:
        """
        Build OAuth 1.0a TBA Authorization header for NetSuite.

        NetSuite TBA signing process:
        1. Collect OAuth parameters (nonce, timestamp, etc.)
        2. Build base string: METHOD&url_encoded(url)&url_encoded(params)
        3. Sign with HMAC-SHA256 using: consumer_secret&token_secret
        4. Base64-encode the signature
        5. Build Authorization header with all OAuth params
        """
        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time()))
        realm = self._account_id.upper().replace("_", "-")

        oauth_params = {
            "oauth_consumer_key": self._consumer_key,
            "oauth_nonce": nonce,
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": timestamp,
            "oauth_token": self._token_id,
            "oauth_version": "1.0",
        }

        # Build signature base string
        sorted_params = "&".join(
            f"{quote(k, safe='')}={quote(v, safe='')}"
            for k, v in sorted(oauth_params.items())
        )
        base_string = "&".join([
            method.upper(),
            quote(url, safe=""),
            quote(sorted_params, safe=""),
        ])

        # Sign
        signing_key = f"{quote(self._consumer_secret, safe='')}&{quote(self._token_secret, safe='')}"
        sig = hmac.new(
            signing_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        import base64
        sig_b64 = base64.b64encode(sig).decode("utf-8")

        # Build header
        auth_parts = ", ".join([
            f'realm="{realm}"',
            f'oauth_consumer_key="{self._consumer_key}"',
            f'oauth_nonce="{nonce}"',
            f'oauth_signature="{quote(sig_b64, safe="")}"',
            'oauth_signature_method="HMAC-SHA256"',
            f'oauth_timestamp="{timestamp}"',
            f'oauth_token="{self._token_id}"',
            'oauth_version="1.0"',
        ])

        return {
            "Authorization": f"OAuth {auth_parts}",
            "Content-Type": "application/json",
        }
