"""
scout/connectors/jira.py — Production Jira Connector (Sprint 34)

Atlassian Jira is the dominant project/issue tracker for PE-backed technology
and software companies. For Miragent, Jira is a signal source for:
  - Engineering velocity and backlog health
  - Offboarding completeness (are departed employees still assigned tickets?)
  - Access and permission changes (project membership)
  - Risk flags: stale P0/P1 bugs, overdue compliance tasks

Jira Cloud and Jira Server/Data Center both expose a REST API, though the auth
mechanism differs:
  Jira Cloud:  Basic Auth using email + API token
               POST /rest/auth/1/session (legacy) — NOT used
               OAuth 2.0 (3-legged) for user-delegated access
  Jira Server: Basic Auth with username + password
               Personal Access Token (Bearer) for modern Server

Most PE portfolio integrations use Cloud with API token (Basic Auth).

API structure:
  Base (Cloud):  https://{instance}.atlassian.net
  Base (Server): https://{server_host}
  - /rest/api/3/issue          → issue search (JQL)
  - /rest/api/3/project        → project list
  - /rest/api/3/user/search    → user search
  - /rest/api/3/group/member   → group members

Pagination:
  Jira uses startAt + maxResults with total field.
  Response: { "issues": [...], "startAt": 0, "maxResults": 100, "total": 5000 }

Rate limits:
  Jira Cloud: 10,000 requests/hour per OAuth token.
  We use 5/sec (300/min) as a safe rate.

Entity types:
  - issue   → all Jira issues (bugs, stories, tasks, epics)
  - project → Jira project records
  - user    → Jira user accounts
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

_PAGE_SIZE = 100  # Jira recommended page size (max 100 for search)
_USER_PAGE_SIZE = 50


class JiraConnector(ConnectorBase):
    """
    Production Atlassian Jira connector.

    Supports Jira Cloud (email + API token) and Jira Server (Basic Auth
    or Personal Access Token).

    Credentials (auth_data keys — Cloud Basic Auth, recommended):
        auth_mode  — "cloud" (default) or "server" or "pat"
        instance   — Jira Cloud instance name, e.g. "acme" (→ acme.atlassian.net)
                     For server: full host, e.g. "jira.acme.internal"
        email      — User email (Cloud only)
        api_token  — Atlassian API token (Cloud) or password (Server)
        username   — Username for Server Basic Auth

    Credentials (auth_data keys — Personal Access Token):
        auth_mode  — "pat"
        instance   — Full Jira host
        token      — Personal Access Token (Bearer)
    """

    CONNECTOR_ID = "jira"
    DISPLAY_NAME = "Atlassian Jira (Production)"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 5.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._auth_mode: str = "cloud"
        self._auth_header: str = ""
        self._base_url: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        self._auth_mode = auth.get("auth_mode", "cloud")
        instance = auth.get("instance", "")

        if not instance:
            logger.error("JiraConnector: missing required auth_data key 'instance'")
            return False

        if self._auth_mode == "cloud":
            self._base_url = f"https://{instance}.atlassian.net"
            return self._authenticate_cloud(auth)
        elif self._auth_mode == "server":
            self._base_url = f"https://{instance}"
            return self._authenticate_server(auth)
        elif self._auth_mode == "pat":
            self._base_url = f"https://{instance}"
            return self._authenticate_pat(auth)
        else:
            logger.error(
                "JiraConnector: unknown auth_mode '%s'. Use 'cloud', 'server', or 'pat'.",
                self._auth_mode,
            )
            return False

    def _authenticate_cloud(self, auth: dict) -> bool:
        email = auth.get("email", "")
        api_token = auth.get("api_token", "")
        if not email or not api_token:
            logger.error("JiraConnector Cloud: missing 'email' or 'api_token'")
            return False

        raw = f"{email}:{api_token}"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()
        return self._validate_connection()

    def _authenticate_server(self, auth: dict) -> bool:
        username = auth.get("username", "")
        api_token = auth.get("api_token", "")
        if not username or not api_token:
            logger.error("JiraConnector Server: missing 'username' or 'api_token'")
            return False

        raw = f"{username}:{api_token}"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()
        return self._validate_connection()

    def _authenticate_pat(self, auth: dict) -> bool:
        token = auth.get("token", "")
        if not token:
            logger.error("JiraConnector PAT: missing 'token'")
            return False
        self._auth_header = f"Bearer {token}"
        return self._validate_connection()

    def _validate_connection(self) -> bool:
        """Validate auth by fetching myself endpoint."""
        try:
            resp = self._http_client.get(
                f"{self._base_url}/rest/api/3/myself",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "JiraConnector authenticated: accountId=%s tenant=%s",
                data.get("accountId", data.get("key", "?")), self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("JiraConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("JiraConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="issue",
                display_name="Jira Issues",
                supports_incremental=True,
                fields=[
                    "id", "key", "summary", "issuetype", "status",
                    "priority", "assignee", "reporter", "project",
                    "labels", "components", "fixVersions",
                    "created", "updated", "resolutiondate",
                    "duedate", "description",
                ],
            ),
            EntitySchema(
                entity_type="project",
                display_name="Jira Projects",
                supports_incremental=False,
                fields=[
                    "id", "key", "name", "projectTypeKey",
                    "lead", "description", "url",
                    "projectCategory", "style",
                ],
            ),
            EntitySchema(
                entity_type="user",
                display_name="Jira Users",
                supports_incremental=False,
                fields=[
                    "accountId", "accountType", "displayName",
                    "emailAddress", "active", "timeZone",
                    "locale", "groups",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type == "issue":
            yield from self._paginate_issues(jql="ORDER BY created ASC")
        elif entity_type == "project":
            yield from self._fetch_projects()
        elif entity_type == "user":
            yield from self._paginate_users()
        else:
            raise ValueError(
                f"JiraConnector does not support entity_type='{entity_type}'. "
                f"Supported: issue, project, user"
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
        Incremental via JQL updated filter for issues.
        Projects and users do not support incremental — fall back to full.
        """
        if entity_type == "issue":
            since_jql = cursor.last_extracted_at.strftime("%Y-%m-%d %H:%M")
            jql = f'updated >= "{since_jql}" ORDER BY updated ASC'

            def _generate() -> Iterator[RawRecord]:
                yield from self._paginate_issues(jql=jql)
        else:
            # Projects and users: full extraction
            def _generate() -> Iterator[RawRecord]:
                yield from self.extract_full(entity_type)

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": cursor.last_extracted_at.isoformat()},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{self._base_url}/rest/api/3/myself",
                headers=self._headers(),
            )
            _ = resp.get("accountId", resp.get("key", ""))
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

    def _paginate_issues(self, jql: str) -> Iterator[RawRecord]:
        """
        Paginate Jira issue search using JQL with startAt/maxResults.

        Response: { "issues": [...], "startAt": 0, "maxResults": 100, "total": N }
        """
        start_at = 0

        while True:
            try:
                resp = self._get(
                    f"{self._base_url}/rest/api/3/search",
                    params={
                        "jql": jql,
                        "startAt": start_at,
                        "maxResults": _PAGE_SIZE,
                        "fields": (
                            "summary,issuetype,status,priority,assignee,reporter,"
                            "project,labels,components,created,updated,resolutiondate,duedate"
                        ),
                    },
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("JiraConnector issue pagination error (startAt=%d): %s", start_at, exc)
                break

            issues = resp.get("issues", [])
            total = resp.get("total", 0)

            for issue in issues:
                yield self._issue_to_raw_record(issue)

            start_at += len(issues)
            if start_at >= total or not issues:
                break

    def _fetch_projects(self) -> Iterator[RawRecord]:
        """Fetch all Jira projects (no pagination needed for most instances)."""
        try:
            resp = self._get(
                f"{self._base_url}/rest/api/3/project/search",
                params={"maxResults": 500},
                headers=self._headers(),
            )
        except Exception as exc:
            logger.error("JiraConnector project fetch error: %s", exc)
            return

        projects = resp.get("values", resp.get("projects", []))
        for project in projects:
            yield self._project_to_raw_record(project)

    def _paginate_users(self) -> Iterator[RawRecord]:
        """Paginate Jira users via /rest/api/3/users/search."""
        start_at = 0

        while True:
            try:
                resp = self._get(
                    f"{self._base_url}/rest/api/3/users/search",
                    params={
                        "startAt": start_at,
                        "maxResults": _USER_PAGE_SIZE,
                    },
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("JiraConnector user pagination error (startAt=%d): %s", start_at, exc)
                break

            # users/search returns a list directly, not wrapped
            users = resp if isinstance(resp, list) else resp.get("values", [])
            for user in users:
                yield self._user_to_raw_record(user)

            if len(users) < _USER_PAGE_SIZE:
                break
            start_at += len(users)

    def _issue_to_raw_record(self, issue: dict[str, Any]) -> RawRecord:
        fields = issue.get("fields", {})
        assignee = fields.get("assignee") or {}
        reporter = fields.get("reporter") or {}
        email = assignee.get("emailAddress") or reporter.get("emailAddress")
        name = assignee.get("displayName") or fields.get("summary") or issue.get("key")
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type="issue",
            source_id=str(issue.get("id", issue.get("key", ""))),
            tenant_id=self.tenant_id,
            payload=issue,
            email_hint=email or None,
            name_hint=name or None,
        )

    def _project_to_raw_record(self, project: dict[str, Any]) -> RawRecord:
        lead = project.get("lead") or {}
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type="project",
            source_id=str(project.get("id", "")),
            tenant_id=self.tenant_id,
            payload=project,
            email_hint=lead.get("emailAddress") or None,
            name_hint=project.get("name") or project.get("key") or None,
        )

    def _user_to_raw_record(self, user: dict[str, Any]) -> RawRecord:
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type="user",
            source_id=str(user.get("accountId", "")),
            tenant_id=self.tenant_id,
            payload=user,
            email_hint=user.get("emailAddress") or None,
            name_hint=user.get("displayName") or None,
        )
