"""
scout/connectors/okta.py — Production Okta Identity Connector (Sprint 31)

Okta is the dominant identity provider in PE-backed mid-market companies. It is
the SSO and app provisioning layer that sits on top of all other systems —
Salesforce, Workday, NetSuite, Slack, GitHub, and every SaaS tool the company uses.

WHY THIS CONNECTOR IS CRITICAL FOR MIRAGENT:
When a Workday or BambooHR record shows "Terminated", Miragent must immediately
verify whether Okta has deactivated the user's account and revoked their app
assignments. Departing employees with active Okta sessions can still access
CRM data, code repos, and financial systems — a major security and compliance risk.

This connector enables the OffboardingSecurityWorker to:
1. Detect employees terminated in HRIS but still ACTIVE in Okta
2. List every app assignment that employee still has
3. Generate a deprovision finding with the app list for immediate human action

Authentication:
  Okta uses API tokens (scoped to a service account) or OAuth 2.0 with PKCE.
  PE portfolio companies typically use API tokens generated in Okta Admin → Security → API.

  Header: Authorization: SSWS {api_token}

API structure:
  Base URL: https://{org_domain}.okta.com/api/v1/
  - /users                   → all users (paginated via Link header)
  - /users/{userId}          → single user detail
  - /users/{userId}/appLinks → apps assigned to this user
  - /groups                  → Okta groups (for org structure)
  - /logs?since=...          → system event log (for incremental)

Pagination:
  Okta uses cursor-based pagination via the Link header:
    Link: <https://...?after=cursor>; rel="next"
  We follow the "next" link until it disappears.

Rate limits:
  Okta enforces 600 requests/minute (10/sec) for most endpoints.
  We use 8/sec (480/min) for safe headroom.

Entity types:
  - user        → Okta user profile + status (ACTIVE/SUSPENDED/DEPROVISIONED)
  - app_user    → per-user app assignments (critical for offboarding)
  - group       → Okta groups (for org structure and policy analysis)
"""

import logging
import re
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

_PAGE_SIZE = 200  # Okta max per page for /users


class OktaConnector(ConnectorBase):
    """
    Production Okta Identity connector.

    The most security-critical connector in Miragent's suite. Enables real-time
    offboarding verification: are terminated employees still active in Okta?
    What apps do they still have access to?

    Credentials (auth_data keys):
        api_token   — Okta API token (Admin → Security → API → Create Token)
        org_domain  — Okta org domain, e.g. "acmecorp" for acmecorp.okta.com
    """

    CONNECTOR_ID = "okta"
    DISPLAY_NAME = "Okta Identity (Production)"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 8.0  # 480/min — below Okta's 600/min limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_token: str = ""
        self._org_domain: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Validate the API token by calling /api/v1/users?limit=1.

        Okta API tokens don't expire, but can be revoked. We verify by
        making a lightweight call rather than a no-op ping endpoint.
        """
        auth = self.credentials.auth_data
        api_token = auth.get("api_token", "")
        org_domain = auth.get("org_domain", "")

        if not api_token or not org_domain:
            logger.error(
                "OktaConnector: missing required auth_data keys "
                "(api_token, org_domain)"
            )
            return False

        self._api_token = api_token
        self._org_domain = org_domain

        try:
            resp = self._http_client.get(
                f"{self._base_url()}/users",
                params={"limit": 1},
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info(
                "OktaConnector authenticated: org=%s.okta.com tenant=%s",
                org_domain, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                logger.error(
                    "OktaConnector: API token rejected (401). "
                    "Verify token is active and has read:users scope. "
                    "tenant=%s", self.tenant_id
                )
            else:
                logger.error(
                    "OktaConnector.authenticate HTTP %d: %s",
                    exc.response.status_code, exc,
                )
            return False
        except Exception as exc:
            logger.exception("OktaConnector.authenticate error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Okta Users",
                supports_incremental=True,
                fields=[
                    # Identity
                    "id", "status", "created", "activated", "lastUpdated",
                    "lastLogin", "passwordChanged",
                    # Profile
                    "profile.login", "profile.email", "profile.firstName",
                    "profile.lastName", "profile.displayName",
                    "profile.title", "profile.department",
                    "profile.organization", "profile.employeeNumber",
                    "profile.manager", "profile.managerId",
                    "profile.mobilePhone", "profile.primaryPhone",
                    "profile.userType", "profile.costCenter",
                    # Credentials
                    "credentials.provider.type",
                ],
            ),
            EntitySchema(
                entity_type="app_user",
                display_name="Okta App Assignments",
                supports_incremental=True,
                fields=[
                    "userId", "appName", "appInstanceId", "label",
                    "created", "lastUpdated", "status",
                    "syncState", "credentials.userName",
                ],
            ),
            EntitySchema(
                entity_type="group",
                display_name="Okta Groups",
                supports_incremental=False,
                fields=[
                    "id", "type", "lastUpdated", "lastMembershipUpdated",
                    "profile.name", "profile.description",
                    "profile.groupType",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Full extraction for Okta entities.

        Users and app_users: paginated via Okta's Link header cursor.
        For app_user, we first get all users, then fetch app links per user —
        this is the critical path for offboarding verification.
        """
        if entity_type == "user":
            yield from self._extract_users()
        elif entity_type == "app_user":
            yield from self._extract_app_users()
        elif entity_type == "group":
            yield from self._extract_groups()
        else:
            raise ValueError(
                f"OktaConnector does not support entity_type='{entity_type}'. "
                f"Supported: user, app_user, group"
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
        Incremental extraction using Okta's lastUpdated filter.

        Okta supports filtering users by lastUpdated >= ISO8601 timestamp.
        This captures recently deactivated accounts — exactly what the
        OffboardingSecurityWorker needs.
        """
        if entity_type not in ("user", "app_user", "group"):
            raise ValueError(
                f"OktaConnector: unsupported entity_type '{entity_type}'"
            )

        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        def _generate() -> Iterator[RawRecord]:
            if entity_type == "user":
                yield from self._extract_users(since_iso=since_iso)
            elif entity_type == "app_user":
                yield from self._extract_app_users(since_iso=since_iso)
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
        """Verify connectivity with a lightweight /users?limit=1 request."""
        start = time.monotonic()
        try:
            resp = self._http_client.get(
                f"{self._base_url()}/users",
                params={"limit": 1},
                headers=self._headers(),
            )
            resp.raise_for_status()
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

    def _base_url(self) -> str:
        return f"https://{self._org_domain}.okta.com/api/v1"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"SSWS {self._api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _extract_users(self, since_iso: str = "") -> Iterator[RawRecord]:
        """
        Paginate Okta users using Link header cursor.

        Okta returns a 'Link' response header with a next URL:
          Link: <https://acme.okta.com/api/v1/users?after=cursor>; rel="next"
        We follow it until rel="next" disappears (last page).
        """
        url = f"{self._base_url()}/users"
        params: dict[str, Any] = {"limit": _PAGE_SIZE}
        if since_iso:
            # Okta filter syntax: filter=lastUpdated gt "2026-01-01T00:00:00.000Z"
            params["filter"] = f'lastUpdated gt "{since_iso}"'

        while url:
            try:
                resp_data, next_url = self._get_with_link_header(url, params)
            except Exception as exc:
                logger.error("OktaConnector users page failed: %s", exc)
                break

            for user in resp_data:
                yield self._user_to_raw_record(user)

            url = next_url
            params = {}  # next_url already has all params embedded

    def _extract_app_users(self, since_iso: str = "") -> Iterator[RawRecord]:
        """
        For every active Okta user, fetch their app assignments.

        This is the most valuable Miragent-specific extraction: when a user is
        terminated in HRIS, we cross-reference here to check whether their
        app access (Salesforce, GitHub, Slack, etc.) is still active in Okta.

        For incremental, we only fetch apps for users modified since the cursor.
        """
        user_filter = ""
        if since_iso:
            user_filter = f'lastUpdated gt "{since_iso}"'

        # First get all relevant users
        url = f"{self._base_url()}/users"
        params: dict[str, Any] = {"limit": _PAGE_SIZE}
        if user_filter:
            params["filter"] = user_filter

        while url:
            try:
                users, next_url = self._get_with_link_header(url, params)
            except Exception as exc:
                logger.error("OktaConnector app_user user list failed: %s", exc)
                break

            for user in users:
                user_id = user.get("id", "")
                if not user_id:
                    continue
                yield from self._fetch_user_app_links(user_id)

            url = next_url
            params = {}

    def _fetch_user_app_links(self, user_id: str) -> Iterator[RawRecord]:
        """Fetch all app assignments for a single Okta user."""
        try:
            apps = self._get(
                f"{self._base_url()}/users/{user_id}/appLinks",
                headers=self._headers(),
            )
        except Exception as exc:
            logger.debug(
                "OktaConnector appLinks fetch for user %s failed: %s",
                user_id, exc,
            )
            return

        if not isinstance(apps, list):
            return

        for app in apps:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type="app_user",
                source_id=f"{user_id}_{app.get('appInstanceId', app.get('id', ''))}",
                tenant_id=self.tenant_id,
                payload={**app, "userId": user_id},
                email_hint=None,
                name_hint=app.get("label"),
            )

    def _extract_groups(self) -> Iterator[RawRecord]:
        """Extract all Okta groups via Link-header pagination."""
        url = f"{self._base_url()}/groups"
        params: dict[str, Any] = {"limit": 200}

        while url:
            try:
                groups, next_url = self._get_with_link_header(url, params)
            except Exception as exc:
                logger.error("OktaConnector groups fetch failed: %s", exc)
                break

            for group in groups:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type="group",
                    source_id=group.get("id", ""),
                    tenant_id=self.tenant_id,
                    payload=group,
                    email_hint=None,
                    name_hint=group.get("profile", {}).get("name"),
                )

            url = next_url
            params = {}

    def _get_with_link_header(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[list[dict], str | None]:
        """
        Make a GET request and parse the Okta Link header for pagination.

        Returns:
            (records_list, next_url_or_None)

        Okta Link header format:
          <https://...?after=cursor>; rel="next", <https://...>; rel="self"
        """
        response = self._http_client.get(
            url,
            params=params,
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            data = []

        # Parse Link header for next page URL
        next_url = None
        link_header = response.headers.get("Link", "")
        if link_header:
            # Match: <URL>; rel="next"
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if match:
                next_url = match.group(1)

        return data, next_url

    def _user_to_raw_record(self, user: dict[str, Any]) -> RawRecord:
        """Convert an Okta user dict to a RawRecord."""
        profile = user.get("profile", {})
        email = profile.get("email") or profile.get("login")
        first = profile.get("firstName", "")
        last = profile.get("lastName", "")
        name = f"{first} {last}".strip() or profile.get("displayName") or None

        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type="user",
            source_id=user.get("id", ""),
            tenant_id=self.tenant_id,
            payload=user,
            email_hint=email,
            name_hint=name,
        )
