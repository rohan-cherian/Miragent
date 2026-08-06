"""
scout/connectors/zoho.py — Production Zoho CRM Connector (Sprint 33)

Zoho CRM is a popular mid-market CRM used by SMB and lower mid-market companies
($5M–$150M ARR), often as a cost-effective alternative to Salesforce. In PE
portfolios, it appears in companies that started small and haven't migrated.

Zoho CRM API:
  Base: https://www.zohoapis.com/crm/v3 (or v3.5 for newer accounts)
  Auth: OAuth 2.0 with refresh token (self-client or user-delegated)
  Entities: Leads, Contacts, Accounts, Deals, Activities (Calls/Tasks/Events)

Authentication:
  Zoho uses a standard OAuth 2.0 refresh_token grant (not client credentials).
  The refresh token must be pre-obtained via Zoho's OAuth flow and stored
  in credentials. The connector exchanges the refresh token for access tokens.

  Token endpoint: https://accounts.zoho.com/oauth/v2/token
  Scopes: ZohoCRM.modules.ALL,ZohoCRM.settings.ALL

  For data center regions:
    US:   https://accounts.zoho.com   / https://www.zohoapis.com
    EU:   https://accounts.zoho.eu    / https://www.zohoapis.eu
    IN:   https://accounts.zoho.in    / https://www.zohoapis.in
    AU:   https://accounts.zoho.com.au / https://www.zohoapis.com.au

Pagination:
  Zoho CRM v3 uses page + per_page with a `more_records` boolean in the `info` block.
  Response: { "data": [...], "info": { "more_records": true, "page": 1, "per_page": 200 } }

Rate limits:
  Free/Standard: 250 API credits per API key per day (roughly 250 calls)
  Professional:  500 credits/day
  Enterprise:    1000 credits/day
  We use 0.5/sec (30/min) as a conservative default.

Entity types:
  - lead         → unqualified leads
  - contact      → individual contacts
  - account      → company/organization accounts
  - deal         → sales opportunities (Zoho calls them "Deals" or "Potentials")
  - activity     → calls, tasks, and events combined
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

_PAGE_SIZE = 200  # Zoho CRM v3 max per_page
_TOKEN_PATH = "/oauth/v2/token"


class ZohoConnector(ConnectorBase):
    """
    Production Zoho CRM connector.

    Uses Zoho's OAuth 2.0 refresh_token grant to obtain short-lived access
    tokens. Requires a pre-issued refresh token stored in credentials.

    Credentials (auth_data keys):
        client_id      — Zoho OAuth client ID
        client_secret  — Zoho OAuth client secret
        refresh_token  — Pre-issued refresh token (long-lived)
        region         — Data center region: "com" (default/US), "eu", "in", "com.au", "jp"
    """

    CONNECTOR_ID = "zoho"
    DISPLAY_NAME = "Zoho CRM (Production)"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 0.5  # 30/min — conservative for Zoho's credit-based limits

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._accounts_base: str = ""
        self._api_base: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Exchange refresh_token for a new access_token via Zoho OAuth.
        The refresh token itself never expires (unless revoked).
        """
        auth = self.credentials.auth_data
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        refresh_token = auth.get("refresh_token", "")
        region = auth.get("region", "com")

        if not all([client_id, client_secret, refresh_token]):
            logger.error(
                "ZohoConnector: missing required auth_data keys "
                "(client_id, client_secret, refresh_token)"
            )
            return False

        # Set regional endpoints
        self._accounts_base = f"https://accounts.zoho.{region}"
        self._api_base = f"https://www.zohoapis.{region}/crm/v3"

        try:
            resp = self._http_client.post(
                f"{self._accounts_base}{_TOKEN_PATH}",
                params={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            token = data.get("access_token", "")
            if not token:
                logger.error(
                    "ZohoConnector: no access_token in response. error=%s",
                    data.get("error"),
                )
                return False

            self._access_token = token
            # Zoho access tokens expire in 3600 seconds
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

            logger.info(
                "ZohoConnector authenticated: region=%s tenant=%s",
                region, self.tenant_id,
            )
            return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                "ZohoConnector.authenticate HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("ZohoConnector.authenticate error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        if time.time() > self._token_expires_at - 300:
            logger.debug("ZohoConnector: refreshing access token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="lead",
                display_name="Zoho CRM Leads",
                supports_incremental=True,
                fields=[
                    "id", "Lead_Source", "First_Name", "Last_Name",
                    "Email", "Phone", "Company", "Title",
                    "Lead_Status", "Rating", "Annual_Revenue",
                    "No_of_Employees", "Description", "Owner",
                    "Created_Time", "Modified_Time",
                ],
            ),
            EntitySchema(
                entity_type="contact",
                display_name="Zoho CRM Contacts",
                supports_incremental=True,
                fields=[
                    "id", "First_Name", "Last_Name", "Email",
                    "Phone", "Mobile", "Title", "Department",
                    "Account_Name", "Mailing_City", "Mailing_Country",
                    "Lead_Source", "Owner",
                    "Created_Time", "Modified_Time",
                ],
            ),
            EntitySchema(
                entity_type="account",
                display_name="Zoho CRM Accounts",
                supports_incremental=True,
                fields=[
                    "id", "Account_Name", "Phone", "Website",
                    "Billing_City", "Billing_Country",
                    "Industry", "Annual_Revenue", "Employees",
                    "Rating", "Account_Type", "Parent_Account",
                    "Owner", "Created_Time", "Modified_Time",
                ],
            ),
            EntitySchema(
                entity_type="deal",
                display_name="Zoho CRM Deals",
                supports_incremental=True,
                fields=[
                    "id", "Deal_Name", "Account_Name", "Contact_Name",
                    "Amount", "Closing_Date", "Stage",
                    "Probability", "Lead_Source", "Type",
                    "Next_Step", "Description",
                    "Owner", "Created_Time", "Modified_Time",
                ],
            ),
            EntitySchema(
                entity_type="activity",
                display_name="Zoho CRM Activities",
                supports_incremental=True,
                fields=[
                    "id", "Subject", "Activity_Type",
                    "Status", "Due_Date", "Description",
                    "Who_Id", "What_Id", "Owner",
                    "Created_Time", "Modified_Time",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """Full extraction via Zoho CRM v3 pagination (page + per_page)."""
        config = self._entity_config(entity_type)
        yield from self._paginate_zoho(
            module=config["module"],
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
        Incremental via Zoho CRM's search API with Modified_Time filter.

        Zoho supports: GET /Contacts/search?criteria=(Modified_Time:greater_than:ISO)
        ISO format: 2026-01-01T00:00:00+00:00
        """
        config = self._entity_config(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        criteria = f"(Modified_Time:greater_than:{since_iso})"

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_zoho(
                module=config["module"],
                entity_type=entity_type,
                criteria=criteria,
                search=True,
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
                f"{self._api_base}/Contacts",
                params={"per_page": 1, "page": 1},
                headers=self._headers(),
            )
            _ = resp.get("data", [])
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
            "Authorization": f"Zoho-oauthtoken {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _entity_config(self, entity_type: str) -> dict[str, str]:
        """Return Zoho CRM module name for entity type."""
        configs = {
            "lead":     {"module": "Leads"},
            "contact":  {"module": "Contacts"},
            "account":  {"module": "Accounts"},
            "deal":     {"module": "Deals"},
            "activity": {"module": "Activities"},
        }
        if entity_type not in configs:
            raise ValueError(
                f"ZohoConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_zoho(
        self,
        module: str,
        entity_type: str,
        criteria: str = "",
        search: bool = False,
    ) -> Iterator[RawRecord]:
        """
        Paginate Zoho CRM results using page/per_page with more_records flag.

        Full extraction:
          GET /{Module}?page=1&per_page=200
          Response: { "data": [...], "info": { "more_records": true, "page": 1, "per_page": 200 } }

        Incremental (search):
          GET /{Module}/search?criteria=(Modified_Time:greater_than:ISO)&page=1&per_page=200
        """
        self._refresh_if_needed()
        page = 1

        while True:
            if search and criteria:
                url = f"{self._api_base}/{module}/search"
                params: dict[str, Any] = {
                    "criteria": criteria,
                    "page": page,
                    "per_page": _PAGE_SIZE,
                }
            else:
                url = f"{self._api_base}/{module}"
                params = {"page": page, "per_page": _PAGE_SIZE}

            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error(
                    "ZohoConnector pagination error (module=%s page=%d): %s",
                    module, page, exc,
                )
                break

            records = resp.get("data", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            info = resp.get("info", {})
            more = info.get("more_records", False)
            if not more or not records:
                break
            page += 1

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        """Convert a Zoho CRM record to RawRecord."""
        source_id = str(record.get("id", ""))
        email = record.get("Email")
        name = (
            record.get("Account_Name")
            or record.get("Deal_Name")
            or record.get("Subject")
            or f"{record.get('First_Name', '')} {record.get('Last_Name', '')}".strip()
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
