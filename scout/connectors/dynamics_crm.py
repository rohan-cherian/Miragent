"""
scout/connectors/dynamics_crm.py — Production Microsoft Dynamics 365 Sales (CRM) Connector (Sprint 33)

Microsoft Dynamics 365 Sales is Microsoft's native CRM platform, tightly integrated
with Microsoft 365, Teams, and Azure. In PE mid-market, it appears in companies
already standardized on Microsoft infrastructure (replacing Salesforce or alongside it).

This connector covers Dynamics 365 Sales (CRM), distinct from Dynamics 365 Finance
(covered by dynamics_365.py). The two share the same authentication mechanism
(Azure AD OAuth 2.0 Client Credentials) but use different APIs:

  Dynamics 365 Sales:
    API: Dynamics 365 Web API (OData v4)
    Base: https://{org}.crm.dynamics.com/api/data/v9.2
    Entities: contacts, leads, accounts, opportunities, activities

  Authentication:
    Azure AD OAuth 2.0 Client Credentials
    Scope: https://{org}.crm.dynamics.com/.default

Pagination:
  OData @odata.nextLink (same pattern as Dynamics F&O and Azure AD Graph).

Rate limits:
  Dynamics 365 Web API: 6000 requests per 5 minutes per connection.
  We use 15/sec (900/min) as a comfortable rate.

Entity types:
  - contact      → contact records (individual people)
  - lead         → unqualified leads
  - account      → company/organization accounts
  - opportunity  → active deals / sales opportunities
  - activity     → email, phone call, task records (activitypointer)
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
_API_VERSION = "v9.2"
_PAGE_SIZE = 5000  # Dynamics Web API max per page


class DynamicsCRMConnector(ConnectorBase):
    """
    Production Microsoft Dynamics 365 Sales (CRM) connector.

    Uses the Dynamics 365 Web API (OData v4) with Azure AD OAuth 2.0
    Client Credentials authentication.

    Credentials (auth_data keys):
        tenant_id      — Azure AD tenant ID (GUID)
        client_id      — Service principal / app registration client ID
        client_secret  — Service principal client secret
        org            — Dynamics 365 org name (e.g. "acme" → acme.crm.dynamics.com)
                         Can also be a full hostname: "acme.crm4.dynamics.com"
    """

    CONNECTOR_ID = "dynamics_crm"
    DISPLAY_NAME = "Microsoft Dynamics 365 Sales CRM (Production)"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 15.0  # 900/min — well within 6000/5min limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
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
        Scope is scoped to the specific Dynamics 365 org instance.
        """
        auth = self.credentials.auth_data
        self._aad_tenant_id = auth.get("tenant_id", "")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        org = auth.get("org", "")

        if not all([self._aad_tenant_id, client_id, client_secret, org]):
            logger.error(
                "DynamicsCRMConnector: missing required auth_data keys "
                "(tenant_id, client_id, client_secret, org)"
            )
            return False

        # Determine base URL — org can be a short name or full hostname
        if "." in org:
            hostname = org
        else:
            hostname = f"{org}.crm.dynamics.com"

        self._base_url = f"https://{hostname}/api/data/{_API_VERSION}"
        scope = f"https://{hostname}/.default"

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
                    "DynamicsCRMConnector: no access_token in response. tenant=%s",
                    self.tenant_id,
                )
                return False

            logger.info(
                "DynamicsCRMConnector authenticated: org=%s tenant=%s",
                org, self.tenant_id,
            )
            return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                "DynamicsCRMConnector.authenticate HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("DynamicsCRMConnector.authenticate error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        if time.time() > self._token_expires_at - 300:
            logger.debug("DynamicsCRMConnector: refreshing access token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="contact",
                display_name="Dynamics CRM Contacts",
                supports_incremental=True,
                fields=[
                    "contactid", "fullname", "firstname", "lastname",
                    "emailaddress1", "emailaddress2", "telephone1",
                    "jobtitle", "department", "accountid",
                    "parentcustomerid", "ownerid",
                    "statecode", "statuscode",
                    "createdon", "modifiedon",
                ],
            ),
            EntitySchema(
                entity_type="lead",
                display_name="Dynamics CRM Leads",
                supports_incremental=True,
                fields=[
                    "leadid", "fullname", "firstname", "lastname",
                    "emailaddress1", "telephone1", "companyname",
                    "jobtitle", "leadsourcecode", "leadqualitycode",
                    "statecode", "statuscode", "subject",
                    "estimatedvalue", "estimatedclosedate",
                    "ownerid", "createdon", "modifiedon",
                ],
            ),
            EntitySchema(
                entity_type="account",
                display_name="Dynamics CRM Accounts",
                supports_incremental=True,
                fields=[
                    "accountid", "name", "emailaddress1",
                    "telephone1", "websiteurl",
                    "address1_city", "address1_country",
                    "industrycode", "revenue", "numberofemployees",
                    "accountcategorycode", "accountclassificationcode",
                    "statecode", "statuscode",
                    "ownerid", "parentaccountid",
                    "createdon", "modifiedon",
                ],
            ),
            EntitySchema(
                entity_type="opportunity",
                display_name="Dynamics CRM Opportunities",
                supports_incremental=True,
                fields=[
                    "opportunityid", "name", "description",
                    "customerid", "parentaccountid", "parentcontactid",
                    "estimatedvalue", "actualvalue",
                    "estimatedclosedate", "actualclosedate",
                    "closeprobability", "stepname",
                    "statecode", "statuscode",
                    "ownerid", "createdon", "modifiedon",
                ],
            ),
            EntitySchema(
                entity_type="activity",
                display_name="Dynamics CRM Activities",
                supports_incremental=True,
                fields=[
                    "activityid", "activitytypecode", "subject",
                    "description", "regardingobjectid",
                    "ownerid", "scheduledstart", "scheduledend",
                    "actualstart", "actualend", "statecode", "statuscode",
                    "createdon", "modifiedon",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """Full extraction via Dynamics Web API OData with @odata.nextLink pagination."""
        config = self._entity_config(entity_type)
        yield from self._paginate_odata(
            endpoint=config["endpoint"],
            entity_type=entity_type,
            select_fields=config.get("select"),
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
        Incremental via OData $filter on modifiedon field.

        Dynamics Web API format: modifiedon ge 2026-01-01T00:00:00Z
        """
        config = self._entity_config(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        odata_filter = f"modifiedon ge {since_iso}"

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_odata(
                endpoint=config["endpoint"],
                entity_type=entity_type,
                odata_filter=odata_filter,
                select_fields=config.get("select"),
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
                f"{self._base_url}/contacts",
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
            "Prefer": f"odata.maxpagesize={_PAGE_SIZE}",
        }

    def _entity_config(self, entity_type: str) -> dict[str, Any]:
        """Return API endpoint and optional field list for entity type."""
        configs: dict[str, dict[str, Any]] = {
            "contact": {
                "endpoint": "/contacts",
                "select": (
                    "contactid,fullname,firstname,lastname,"
                    "emailaddress1,emailaddress2,telephone1,"
                    "jobtitle,department,statecode,statuscode,"
                    "createdon,modifiedon"
                ),
            },
            "lead": {
                "endpoint": "/leads",
                "select": (
                    "leadid,fullname,firstname,lastname,"
                    "emailaddress1,telephone1,companyname,"
                    "jobtitle,leadsourcecode,statecode,statuscode,"
                    "estimatedvalue,estimatedclosedate,"
                    "createdon,modifiedon"
                ),
            },
            "account": {
                "endpoint": "/accounts",
                "select": (
                    "accountid,name,emailaddress1,telephone1,websiteurl,"
                    "address1_city,address1_country,industrycode,revenue,"
                    "numberofemployees,statecode,statuscode,"
                    "createdon,modifiedon"
                ),
            },
            "opportunity": {
                "endpoint": "/opportunities",
                "select": (
                    "opportunityid,name,description,"
                    "estimatedvalue,actualvalue,"
                    "estimatedclosedate,actualclosedate,"
                    "closeprobability,stepname,"
                    "statecode,statuscode,"
                    "createdon,modifiedon"
                ),
            },
            "activity": {
                "endpoint": "/activitypointers",
                "select": (
                    "activityid,activitytypecode,subject,description,"
                    "scheduledstart,scheduledend,"
                    "actualstart,actualend,"
                    "statecode,statuscode,"
                    "createdon,modifiedon"
                ),
            },
        }

        if entity_type not in configs:
            raise ValueError(
                f"DynamicsCRMConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_odata(
        self,
        endpoint: str,
        entity_type: str,
        odata_filter: str = "",
        select_fields: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Dynamics 365 Web API OData results via @odata.nextLink.

        Response structure:
          { "value": [...records...], "@odata.nextLink": "..." }
        """
        self._refresh_if_needed()
        url: str | None = f"{self._base_url}{endpoint}"
        params: dict[str, Any] = {"$top": _PAGE_SIZE}
        if odata_filter:
            params["$filter"] = odata_filter
        if select_fields:
            params["$select"] = select_fields

        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error(
                    "DynamicsCRMConnector pagination error (endpoint=%s): %s",
                    endpoint, exc,
                )
                break

            records = resp.get("value", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            url = resp.get("@odata.nextLink")
            params = {}  # nextLink has params embedded

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        """Convert a Dynamics CRM record to RawRecord."""
        source_id = str(
            record.get("contactid")
            or record.get("leadid")
            or record.get("accountid")
            or record.get("opportunityid")
            or record.get("activityid")
            or ""
        )
        email = (
            record.get("emailaddress1")
            or record.get("emailaddress2")
        )
        name = (
            record.get("fullname")
            or record.get("name")
            or f"{record.get('firstname', '')} {record.get('lastname', '')}".strip()
            or record.get("subject")
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
