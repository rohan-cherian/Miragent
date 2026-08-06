"""
scout/connectors/azure_ad.py — Production Azure AD / Microsoft Entra Connector (Sprint 31)

Azure Active Directory (now Microsoft Entra ID) is the identity backbone of
Microsoft-stack PE portfolio companies. If a company runs M365, Teams, and
Dynamics 365, Azure AD is their user directory and SSO provider.

WHY THIS CONNECTOR MATTERS:
Like Okta, Azure AD is the gatekeeper for app access. In M365-heavy companies,
terminating an Azure AD account also revokes access to Teams, SharePoint,
Exchange email, and any Azure-integrated SaaS tools. Miragent's offboarding
worker needs to verify Azure AD status when HRIS shows a termination.

Key difference from Okta:
  Okta is an external IdP that syncs to cloud apps.
  Azure AD is Microsoft's cloud directory that can also sync TO on-prem AD.
  Some companies use both — Okta federating to Azure AD. Miragent handles both.

Authentication:
  Azure AD uses OAuth 2.0 Client Credentials flow against Microsoft Identity Platform.
  Service principal with application permissions (not delegated — runs without a user).

  Token endpoint: https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
  Graph API base: https://graph.microsoft.com/v1.0/

  Required permissions (Application type):
    User.Read.All, Group.Read.All, Directory.Read.All

API structure (Microsoft Graph):
  - /users                             → paginated user list
  - /users/{id}/appRoleAssignments     → app assignments per user
  - /groups                            → Azure AD groups
  - /auditLogs/signIns                 → sign-in logs (premium feature)

Pagination:
  Graph API uses OData @odata.nextLink for pagination.
  Each page returns up to 999 users ($top=999).

Rate limits:
  Microsoft Graph enforces 10,000 requests per 10 minutes per app.
  We use 15/sec (900/min) to stay well below the limit.

Entity types:
  - user              → Azure AD user (status: enabled/disabled)
  - app_assignment    → per-user app role assignments
  - group             → Azure AD groups / M365 groups
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

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TOKEN_BASE = "https://login.microsoftonline.com"
_PAGE_SIZE = 999  # Graph API max for user list


class AzureADConnector(ConnectorBase):
    """
    Production Azure AD / Microsoft Entra connector via Microsoft Graph API.

    Extracts users, app assignments, and groups for cross-system identity
    verification — especially critical for M365-native PE portfolio companies.

    Credentials (auth_data keys):
        tenant_id       — Azure AD tenant ID (GUID), e.g. "abc123-..."
        client_id       — Service principal application (client) ID
        client_secret   — Service principal client secret
    """

    CONNECTOR_ID = "azure_ad"
    DISPLAY_NAME = "Azure AD / Microsoft Entra (Production)"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 15.0  # 900/min — safe below Graph's 10k/10min limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._aad_tenant_id: str = ""  # Azure tenant ID (different from Miragent tenant_id)
        self._token_expires_at: float = 0.0

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Obtain an OAuth 2.0 access token via Client Credentials flow.

        Uses Microsoft Identity Platform v2.0 endpoint. The scope for
        Graph API is always "https://graph.microsoft.com/.default".
        """
        auth = self.credentials.auth_data
        aad_tenant = auth.get("tenant_id", "")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")

        if not all([aad_tenant, client_id, client_secret]):
            logger.error(
                "AzureADConnector: missing required auth_data keys "
                "(tenant_id, client_id, client_secret)"
            )
            return False

        self._aad_tenant_id = aad_tenant

        try:
            resp = self._http_client.post(
                f"{_TOKEN_BASE}/{aad_tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            token_data = resp.json()
            self._access_token = token_data.get("access_token", "")
            expires_in = token_data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

            if not self._access_token:
                logger.error(
                    "AzureADConnector: token response missing access_token. "
                    "tenant=%s", self.tenant_id
                )
                return False

            logger.info(
                "AzureADConnector authenticated: aad_tenant=%s miragent_tenant=%s",
                aad_tenant[:8] + "...", self.tenant_id,
            )
            return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                "AzureADConnector.authenticate HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return False
        except Exception as exc:
            logger.exception("AzureADConnector.authenticate error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        """Re-authenticate if the token is within 5 minutes of expiry."""
        if time.time() > self._token_expires_at - 300:
            logger.debug("AzureADConnector: refreshing access token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Azure AD Users",
                supports_incremental=True,
                fields=[
                    # Identity
                    "id", "userPrincipalName", "displayName",
                    "givenName", "surname", "mail",
                    # Employment
                    "jobTitle", "department", "companyName",
                    "employeeId", "employeeType", "employeeHireDate",
                    "employeeLeaveDateTime",
                    # Status
                    "accountEnabled", "createdDateTime", "deletedDateTime",
                    "lastPasswordChangeDateTime", "onPremisesSyncEnabled",
                    # Contact
                    "mobilePhone", "businessPhones",
                    # Org
                    "manager", "officeLocation", "usageLocation",
                    # Auth
                    "userType", "assignedLicenses",
                ],
            ),
            EntitySchema(
                entity_type="app_assignment",
                display_name="Azure AD App Role Assignments",
                supports_incremental=True,
                fields=[
                    "userId", "appRoleId", "principalId",
                    "resourceId", "resourceDisplayName",
                    "principalDisplayName", "createdDateTime",
                ],
            ),
            EntitySchema(
                entity_type="group",
                display_name="Azure AD Groups",
                supports_incremental=False,
                fields=[
                    "id", "displayName", "description", "groupTypes",
                    "mail", "mailEnabled", "securityEnabled",
                    "membershipRule", "createdDateTime",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Full extraction via Microsoft Graph API with @odata.nextLink pagination.
        """
        if entity_type == "user":
            yield from self._extract_users()
        elif entity_type == "app_assignment":
            yield from self._extract_app_assignments()
        elif entity_type == "group":
            yield from self._extract_groups()
        else:
            raise ValueError(
                f"AzureADConnector does not support entity_type='{entity_type}'. "
                f"Supported: user, app_assignment, group"
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
        Incremental extraction using Graph API's $filter with lastModifiedDateTime.

        For users: filter=lastModifiedDateTime ge YYYY-MM-DDTHH:MM:SSZ
        This captures recently disabled accounts — key for offboarding detection.
        """
        if entity_type not in ("user", "app_assignment", "group"):
            raise ValueError(
                f"AzureADConnector: unsupported entity_type '{entity_type}'"
            )

        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _generate() -> Iterator[RawRecord]:
            if entity_type == "user":
                yield from self._extract_users(since_iso=since_iso)
            elif entity_type == "app_assignment":
                yield from self._extract_app_assignments(since_iso=since_iso)
            else:
                yield from self._extract_groups()

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
        """Verify connectivity with a lightweight /users?$top=1 request."""
        start = time.monotonic()
        try:
            self._refresh_if_needed()
            resp = self._get(
                f"{_GRAPH_BASE}/users",
                params={"$top": 1, "$select": "id,displayName"},
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
        }

    def _extract_users(self, since_iso: str = "") -> Iterator[RawRecord]:
        """
        Paginate Azure AD users using @odata.nextLink.

        Graph response structure:
          {
            "@odata.context": "...",
            "@odata.nextLink": "https://...?$skiptoken=...",
            "value": [...users...]
          }

        We follow @odata.nextLink until it disappears.
        """
        self._refresh_if_needed()
        params: dict[str, Any] = {
            "$top": _PAGE_SIZE,
            "$select": ",".join([
                "id", "userPrincipalName", "displayName", "givenName", "surname",
                "mail", "jobTitle", "department", "accountEnabled",
                "employeeId", "employeeType", "employeeHireDate",
                "createdDateTime", "mobilePhone", "userType",
            ]),
        }
        if since_iso:
            params["$filter"] = f"lastModifiedDateTime ge {since_iso}"

        url: str | None = f"{_GRAPH_BASE}/users"
        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error("AzureADConnector users page failed: %s", exc)
                break

            users = resp.get("value", [])
            for user in users:
                yield self._user_to_raw_record(user)

            url = resp.get("@odata.nextLink")
            params = {}  # next link has params embedded

    def _extract_app_assignments(self, since_iso: str = "") -> Iterator[RawRecord]:
        """
        Fetch app role assignments for each user.

        Strategy: get all users, then for each user fetch their
        appRoleAssignments. This is the same pattern as Okta's appLinks.
        For incremental, filter users by modification date first.
        """
        self._refresh_if_needed()
        params: dict[str, Any] = {
            "$top": _PAGE_SIZE,
            "$select": "id,userPrincipalName,displayName,accountEnabled",
        }
        if since_iso:
            params["$filter"] = f"lastModifiedDateTime ge {since_iso}"

        url: str | None = f"{_GRAPH_BASE}/users"
        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error("AzureADConnector app_assignment user list failed: %s", exc)
                break

            users = resp.get("value", [])
            for user in users:
                user_id = user.get("id", "")
                if user_id:
                    yield from self._fetch_user_app_assignments(user_id)

            url = resp.get("@odata.nextLink")
            params = {}

    def _fetch_user_app_assignments(self, user_id: str) -> Iterator[RawRecord]:
        """Fetch app role assignments for a single Azure AD user."""
        try:
            resp = self._get(
                f"{_GRAPH_BASE}/users/{user_id}/appRoleAssignments",
                headers=self._headers(),
            )
        except Exception as exc:
            logger.debug(
                "AzureADConnector appRoleAssignments for %s failed: %s",
                user_id, exc,
            )
            return

        assignments = resp.get("value", [])
        for assignment in assignments:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type="app_assignment",
                source_id=assignment.get("id", ""),
                tenant_id=self.tenant_id,
                payload={**assignment, "userId": user_id},
                email_hint=None,
                name_hint=assignment.get("resourceDisplayName"),
            )

    def _extract_groups(self) -> Iterator[RawRecord]:
        """Extract all Azure AD groups via @odata.nextLink pagination."""
        self._refresh_if_needed()
        url: str | None = f"{_GRAPH_BASE}/groups"
        params: dict[str, Any] = {
            "$top": 999,
            "$select": "id,displayName,description,groupTypes,mail,securityEnabled,createdDateTime",
        }

        while url:
            try:
                resp = self._get(url, params=params, headers=self._headers())
            except Exception as exc:
                logger.error("AzureADConnector groups fetch failed: %s", exc)
                break

            groups = resp.get("value", [])
            for group in groups:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type="group",
                    source_id=group.get("id", ""),
                    tenant_id=self.tenant_id,
                    payload=group,
                    email_hint=group.get("mail"),
                    name_hint=group.get("displayName"),
                )

            url = resp.get("@odata.nextLink")
            params = {}

    def _user_to_raw_record(self, user: dict[str, Any]) -> RawRecord:
        """Convert an Azure AD user dict to a RawRecord."""
        first = user.get("givenName", "")
        last = user.get("surname", "")
        name = f"{first} {last}".strip() or user.get("displayName") or None
        email = user.get("mail") or user.get("userPrincipalName")

        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type="user",
            source_id=user.get("id", ""),
            tenant_id=self.tenant_id,
            payload=user,
            email_hint=email,
            name_hint=name,
        )
