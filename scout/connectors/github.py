"""
scout/connectors/github.py — Production GitHub Connector (Sprint 57)

GitHub is the dominant SCM/collaboration platform for PE-backed software
companies. For Miragent, GitHub is the primary signal source for R&D health:
  - DORA metrics (Deployment Frequency, Lead Time, CFR, MTTR)
  - Engineering velocity (PR cycle time, review lag, throughput)
  - Bus-factor risk (single-contributor repos)
  - Technical debt signals (stale PRs, open issues accumulation)
  - Security posture (secret scanning alerts, Dependabot findings)

Auth:
  GitHub App (preferred) — fine-grained, per-org, audit-friendly
  Personal Access Token — simpler, sufficient for read-only metrics
  GitHub Enterprise — same REST API, different base URL

API:
  REST v3: https://api.github.com
  GraphQL v4: https://api.github.com/graphql  (future: richer traversal)

Rate limits:
  PAT/App: 5,000 requests/hour authenticated
  We use 10/sec as a safe rate (36,000/hour — well within limit).

Pagination:
  Link header: rel="next" with cursor URL, up to 100 per page.

Entity types:
  - repository  → org repos
  - pull_request → PRs (open and recently merged)
  - deployment  → production deployment events
  - incident    → GitHub Issues tagged as incidents (configurable label)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

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

_PAGE_SIZE = 100
_INCIDENT_LABEL = "incident"  # GitHub Issues label used to track production incidents


class GitHubConnector(ConnectorBase):
    """
    Production GitHub connector using the GitHub REST API v3.

    Credentials (auth_data keys):
        auth_mode   — "pat" (default) or "github_app"
        token       — Personal Access Token (classic or fine-grained)
        org         — GitHub organization name (e.g. "acmecorp")
        base_url    — Override for GitHub Enterprise (e.g. "https://github.acmecorp.com/api/v3")

    For GitHub App (advanced):
        app_id         — GitHub App ID
        private_key    — PEM private key string
        installation_id — Installation ID for the target org
    """

    CONNECTOR_ID = "github"
    DISPLAY_NAME = "GitHub (Production)"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 10.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._token: str = ""
        self._org: str = ""
        self._base_url: str = "https://api.github.com"

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        self._org = auth.get("org", "")
        self._base_url = auth.get("base_url", "https://api.github.com").rstrip("/")

        if not self._org:
            logger.error("GitHubConnector: missing required auth_data key 'org'")
            return False

        auth_mode = auth.get("auth_mode", "pat")

        if auth_mode == "pat":
            self._token = auth.get("token", "")
            if not self._token:
                logger.error("GitHubConnector PAT: missing 'token'")
                return False
        elif auth_mode == "github_app":
            logger.error("GitHubConnector: github_app auth not yet implemented")
            return False
        else:
            logger.error("GitHubConnector: unknown auth_mode '%s'. Use 'pat' or 'github_app'.", auth_mode)
            return False

        return self._validate_connection()

    def _validate_connection(self) -> bool:
        try:
            resp = self._get(
                f"{self._base_url}/orgs/{self._org}",
                headers=self._headers(),
            )
            logger.info(
                "GitHubConnector authenticated: org=%s login=%s tenant=%s",
                self._org, resp.get("login", "?"), self.tenant_id,
            )
            return True
        except Exception as exc:
            logger.exception("GitHubConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="repository",
                display_name="GitHub Repositories",
                supports_incremental=False,
                fields=["id", "name", "full_name", "language", "pushed_at",
                        "open_issues_count", "default_branch", "topics"],
            ),
            EntitySchema(
                entity_type="pull_request",
                display_name="Pull Requests",
                supports_incremental=True,
                fields=["id", "number", "repo_name", "title", "state", "author",
                        "created_at", "merged_at", "cycle_time_hours", "additions",
                        "deletions", "changed_files"],
            ),
            EntitySchema(
                entity_type="deployment",
                display_name="Deployments",
                supports_incremental=True,
                fields=["id", "repo_name", "environment", "status", "created_at",
                        "duration_seconds", "triggered_by"],
            ),
            EntitySchema(
                entity_type="incident",
                display_name="Production Incidents",
                supports_incremental=True,
                fields=["id", "repo_name", "severity", "title", "started_at",
                        "resolved_at", "ttr_hours"],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type == "repository":
            yield from self._paginate_repos()
        elif entity_type == "pull_request":
            yield from self._paginate_all_prs(since=None)
        elif entity_type == "deployment":
            yield from self._paginate_all_deployments(since=None)
        elif entity_type == "incident":
            yield from self._paginate_incidents(since=None)
        else:
            raise ValueError(
                f"GitHubConnector does not support entity_type='{entity_type}'. "
                f"Supported: repository, pull_request, deployment, incident"
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        since = cursor.last_extracted_at

        def _generate() -> Iterator[RawRecord]:
            if entity_type == "repository":
                yield from self._paginate_repos()
            elif entity_type == "pull_request":
                yield from self._paginate_all_prs(since=since)
            elif entity_type == "deployment":
                yield from self._paginate_all_deployments(since=since)
            elif entity_type == "incident":
                yield from self._paginate_incidents(since=since)

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": since.isoformat()},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{self._base_url}/rate_limit",
                headers=self._headers(),
            )
            remaining = resp.get("rate", {}).get("remaining", 0)
            latency_ms = (time.monotonic() - start) * 1000
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
                detail={"rate_limit_remaining": remaining},
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
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _paginate(self, url: str, params: dict | None = None) -> Iterator[dict]:
        """Generic Link-header paginator for GitHub list endpoints."""
        while url:
            resp = self._http_client.get(
                url,
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                yield from data
            else:
                yield data
                break
            # Follow Link: <url>; rel="next"
            link = resp.headers.get("Link", "")
            url = ""
            params = None
            for part in link.split(","):
                part = part.strip()
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break

    def _paginate_repos(self) -> Iterator[RawRecord]:
        url = f"{self._base_url}/orgs/{self._org}/repos"
        params = {"type": "all", "per_page": _PAGE_SIZE, "sort": "pushed"}
        for repo in self._paginate(url, params):
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type="repository",
                source_id=str(repo["id"]),
                tenant_id=self.tenant_id,
                payload=repo,
                name_hint=repo.get("name"),
            )

    def _paginate_all_prs(self, since: datetime | None) -> Iterator[RawRecord]:
        """Fetch PRs across all repos."""
        repos_url = f"{self._base_url}/orgs/{self._org}/repos"
        for repo in self._paginate(repos_url, {"type": "all", "per_page": _PAGE_SIZE}):
            repo_name = repo.get("name", "")
            yield from self._paginate_repo_prs(repo_name, since)

    def _paginate_repo_prs(self, repo_name: str, since: datetime | None) -> Iterator[RawRecord]:
        url = f"{self._base_url}/repos/{self._org}/{repo_name}/pulls"
        params: dict[str, Any] = {"state": "all", "per_page": _PAGE_SIZE, "sort": "updated", "direction": "desc"}
        for pr in self._paginate(url, params):
            created = pr.get("created_at", "")
            if since and created:
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if ts.replace(tzinfo=None) < since:
                        return
                except (ValueError, TypeError):
                    pass
            # Compute cycle time
            merged_at = pr.get("merged_at")
            cycle_hours = None
            if merged_at and pr.get("created_at"):
                try:
                    t0 = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
                    cycle_hours = (t1 - t0).total_seconds() / 3600
                except (ValueError, TypeError):
                    pass
            pr["repo_name"] = repo_name
            pr["cycle_time_hours"] = cycle_hours
            author = (pr.get("user") or {}).get("login", "")
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type="pull_request",
                source_id=str(pr["id"]),
                tenant_id=self.tenant_id,
                payload=pr,
                name_hint=pr.get("title"),
                email_hint=None,  # GitHub login ≠ email without extra call
            )

    def _paginate_all_deployments(self, since: datetime | None) -> Iterator[RawRecord]:
        repos_url = f"{self._base_url}/orgs/{self._org}/repos"
        for repo in self._paginate(repos_url, {"type": "all", "per_page": _PAGE_SIZE}):
            repo_name = repo.get("name", "")
            url = f"{self._base_url}/repos/{self._org}/{repo_name}/deployments"
            params: dict[str, Any] = {"environment": "production", "per_page": _PAGE_SIZE}
            try:
                for dep in self._paginate(url, params):
                    created = dep.get("created_at", "")
                    if since and created:
                        try:
                            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            if ts.replace(tzinfo=None) < since:
                                break
                        except (ValueError, TypeError):
                            pass
                    dep["repo_name"] = repo_name
                    yield RawRecord(
                        connector_id=self.CONNECTOR_ID,
                        entity_type="deployment",
                        source_id=str(dep["id"]),
                        tenant_id=self.tenant_id,
                        payload=dep,
                        name_hint=repo_name,
                    )
            except Exception as exc:
                logger.warning("GitHubConnector: deployments error for %s: %s", repo_name, exc)

    def _paginate_incidents(self, since: datetime | None) -> Iterator[RawRecord]:
        """Fetch Issues labelled 'incident' across the org as production incident records."""
        # GitHub search API: issues across org with label
        url = f"{self._base_url}/search/issues"
        query = f"org:{self._org} label:{_INCIDENT_LABEL} is:issue"
        if since:
            query += f" updated:>={since.strftime('%Y-%m-%d')}"
        params: dict[str, Any] = {"q": query, "per_page": _PAGE_SIZE, "sort": "updated", "order": "desc"}
        for issue in self._paginate(url, params):
            # Search returns {total_count, items}
            if "items" in issue:
                for item in issue["items"]:
                    yield self._issue_to_incident(item)
            elif "number" in issue:
                yield self._issue_to_incident(issue)

    def _issue_to_incident(self, issue: dict) -> RawRecord:
        """Convert a GitHub Issue to an incident RawRecord."""
        created = issue.get("created_at", "")
        closed = issue.get("closed_at")
        ttr_hours = None
        if created and closed:
            try:
                t0 = datetime.fromisoformat(created.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(closed.replace("Z", "+00:00"))
                ttr_hours = (t1 - t0).total_seconds() / 3600
            except (ValueError, TypeError):
                pass
        repo_url = issue.get("repository_url", "")
        repo_name = repo_url.split("/")[-1] if repo_url else ""
        enriched = {
            **issue,
            "repo_name": repo_name,
            "started_at": created,
            "resolved_at": closed,
            "ttr_hours": ttr_hours,
        }
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type="incident",
            source_id=str(issue["id"]),
            tenant_id=self.tenant_id,
            payload=enriched,
            name_hint=issue.get("title"),
        )
