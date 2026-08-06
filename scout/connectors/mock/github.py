"""
scout/connectors/mock/github.py — Mock GitHub connector.

Provides realistic synthetic data for DORA metrics and engineering velocity
analysis. Entity types:
  - repository  — GitHub repos with language, size, activity metadata
  - pull_request — PRs with cycle time, review lag, and merge data
  - deployment   — production deployments with success/failure status
  - incident     — production incidents (linked to failed deployments)
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
import random

from scout.connectors.base import ConnectorBase
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ConnectorHealth,
    EntitySchema,
    ExtractionCursor,
    RawRecord,
)

# ── Mock Repositories ─────────────────────────────────────────────────────────

_MOCK_REPOS = [
    {
        "id": "gh-repo-001", "name": "core-platform", "full_name": "acmecorp/core-platform",
        "language": "Python", "default_branch": "main", "private": True,
        "stargazers_count": 0, "open_issues_count": 12, "size": 45000,
        "pushed_at": "2026-05-17T14:22:00Z", "created_at": "2022-01-15T00:00:00Z",
        "topics": ["backend", "api", "core"],
        "team": "platform", "primary_owner": "raj.krishnamurthy@acmecorp.com",
    },
    {
        "id": "gh-repo-002", "name": "frontend-app", "full_name": "acmecorp/frontend-app",
        "language": "TypeScript", "default_branch": "main", "private": True,
        "stargazers_count": 0, "open_issues_count": 8, "size": 22000,
        "pushed_at": "2026-05-17T11:05:00Z", "created_at": "2022-03-01T00:00:00Z",
        "topics": ["frontend", "react", "typescript"],
        "team": "product", "primary_owner": "sarah.chen@acmecorp.com",
    },
    {
        "id": "gh-repo-003", "name": "data-pipeline", "full_name": "acmecorp/data-pipeline",
        "language": "Python", "default_branch": "main", "private": True,
        "stargazers_count": 0, "open_issues_count": 5, "size": 18000,
        "pushed_at": "2026-05-14T09:30:00Z", "created_at": "2022-06-01T00:00:00Z",
        "topics": ["data", "etl", "pipeline"],
        "team": "data", "primary_owner": "james.liu@acmecorp.com",
    },
    {
        "id": "gh-repo-004", "name": "auth-service", "full_name": "acmecorp/auth-service",
        "language": "Go", "default_branch": "main", "private": True,
        "stargazers_count": 0, "open_issues_count": 3, "size": 8500,
        "pushed_at": "2026-05-10T16:00:00Z", "created_at": "2023-02-01T00:00:00Z",
        "topics": ["auth", "security", "go"],
        "team": "security", "primary_owner": "carlos.mendez@acmecorp.com",
    },
    {
        "id": "gh-repo-005", "name": "reporting-service", "full_name": "acmecorp/reporting-service",
        "language": "Python", "default_branch": "main", "private": True,
        "stargazers_count": 0, "open_issues_count": 21, "size": 32000,
        "pushed_at": "2026-04-28T10:00:00Z", "created_at": "2021-11-01T00:00:00Z",
        "topics": ["reporting", "analytics"],
        "team": "data", "primary_owner": "thomas.brennan@acmecorp.com",
    },
    {
        "id": "gh-repo-006", "name": "mobile-app", "full_name": "acmecorp/mobile-app",
        "language": "Swift", "default_branch": "main", "private": True,
        "stargazers_count": 0, "open_issues_count": 15, "size": 41000,
        "pushed_at": "2026-05-16T08:00:00Z", "created_at": "2023-05-01T00:00:00Z",
        "topics": ["mobile", "ios", "swift"],
        "team": "product", "primary_owner": "aisha.mohammed@acmecorp.com",
    },
    {
        "id": "gh-repo-007", "name": "legacy-billing", "full_name": "acmecorp/legacy-billing",
        "language": "Java", "default_branch": "master", "private": True,
        "stargazers_count": 0, "open_issues_count": 47, "size": 125000,
        "pushed_at": "2026-03-15T00:00:00Z", "created_at": "2018-04-01T00:00:00Z",
        "topics": ["billing", "legacy"],
        "team": "finance-eng", "primary_owner": "thomas.brennan@acmecorp.com",
    },
]

# ── Mock Pull Requests ────────────────────────────────────────────────────────
# Simulate a 90-day window of PR activity with realistic cycle times.

def _generate_prs() -> list[dict]:
    prs = []
    pr_id = 1
    now = datetime(2026, 5, 17, 18, 0, 0)

    scenarios = [
        # (repo_id, repo_name, typical_cycle_hrs, review_lag_hrs, author, reviewer)
        ("gh-repo-001", "core-platform",     18, 4,  "raj.krishnamurthy@acmecorp.com", "sarah.chen@acmecorp.com"),
        ("gh-repo-002", "frontend-app",      12, 2,  "sarah.chen@acmecorp.com",        "elena.vasquez@acmecorp.com"),
        ("gh-repo-003", "data-pipeline",     36, 12, "james.liu@acmecorp.com",         "raj.krishnamurthy@acmecorp.com"),
        ("gh-repo-004", "auth-service",      8,  3,  "carlos.mendez@acmecorp.com",     "raj.krishnamurthy@acmecorp.com"),
        ("gh-repo-005", "reporting-service", 72, 24, "thomas.brennan@acmecorp.com",    "james.liu@acmecorp.com"),
        ("gh-repo-006", "mobile-app",        24, 6,  "aisha.mohammed@acmecorp.com",    "sarah.chen@acmecorp.com"),
        ("gh-repo-007", "legacy-billing",    96, 48, "thomas.brennan@acmecorp.com",    "james.liu@acmecorp.com"),
    ]

    for repo_id, repo_name, cycle_hrs, review_lag_hrs, author, reviewer in scenarios:
        # Generate 8-20 PRs per repo over 90 days
        count = random.randint(8, 20)
        for _ in range(count):
            # Spread across past 90 days
            opened_offset = random.randint(1, 90 * 24)
            opened_at = now - timedelta(hours=opened_offset)

            # Add jitter to cycle time (±50%)
            actual_cycle = cycle_hrs * (0.5 + random.random())
            # Some PRs are still open
            is_merged = random.random() > 0.12
            merged_at = None
            if is_merged and opened_offset > actual_cycle:
                merged_at = (opened_at + timedelta(hours=actual_cycle)).isoformat() + "Z"

            first_review_at = None
            if is_merged:
                first_review_lag = review_lag_hrs * (0.5 + random.random())
                first_review_at = (opened_at + timedelta(hours=first_review_lag)).isoformat() + "Z"

            prs.append({
                "id": f"gh-pr-{pr_id:04d}",
                "number": pr_id,
                "repo_id": repo_id,
                "repo_name": repo_name,
                "title": f"feat: improvement #{pr_id} in {repo_name}",
                "state": "merged" if is_merged else "open",
                "author": author,
                "reviewer": reviewer if is_merged else None,
                "created_at": opened_at.isoformat() + "Z",
                "merged_at": merged_at,
                "first_review_at": first_review_at,
                "cycle_time_hours": actual_cycle if is_merged else None,
                "review_lag_hours": review_lag_hrs * (0.5 + random.random()) if is_merged else None,
                "additions": random.randint(5, 800),
                "deletions": random.randint(2, 400),
                "changed_files": random.randint(1, 25),
            })
            pr_id += 1

    return prs


# ── Mock Deployments ──────────────────────────────────────────────────────────

def _generate_deployments() -> list[dict]:
    deployments = []
    dep_id = 1
    now = datetime(2026, 5, 17, 18, 0, 0)

    # Deployment frequency per repo over 90 days (total deployments)
    repo_deploy_config = [
        ("gh-repo-001", "core-platform",     45, 0.04),   # frequent, low failure
        ("gh-repo-002", "frontend-app",      60, 0.03),   # very frequent
        ("gh-repo-003", "data-pipeline",     20, 0.10),   # moderate, higher failure
        ("gh-repo-004", "auth-service",      30, 0.02),   # good cadence
        ("gh-repo-005", "reporting-service", 8,  0.18),   # infrequent, high failure!
        ("gh-repo-006", "mobile-app",        15, 0.08),
        ("gh-repo-007", "legacy-billing",    4,  0.25),   # very infrequent, 25% failure rate!
    ]

    for repo_id, repo_name, count, failure_rate in repo_deploy_config:
        for _ in range(count):
            deployed_offset = random.randint(0, 90 * 24 * 60)  # minutes
            deployed_at = now - timedelta(minutes=deployed_offset)
            is_failure = random.random() < failure_rate
            deployments.append({
                "id": f"gh-dep-{dep_id:04d}",
                "repo_id": repo_id,
                "repo_name": repo_name,
                "environment": "production",
                "status": "failure" if is_failure else "success",
                "created_at": deployed_at.isoformat() + "Z",
                "duration_seconds": random.randint(120, 1200),
                "triggered_by": "ci-system",
            })
            dep_id += 1

    return sorted(deployments, key=lambda d: d["created_at"], reverse=True)


# ── Mock Incidents ────────────────────────────────────────────────────────────

def _generate_incidents() -> list[dict]:
    incidents = []
    now = datetime(2026, 5, 17, 18, 0, 0)
    inc_id = 1

    # (repo, severity, ttrs_hrs list)
    incident_config = [
        ("core-platform",     "P1", [1.5, 0.8, 2.2]),
        ("core-platform",     "P2", [4.0, 3.5]),
        ("data-pipeline",     "P1", [6.0, 3.0]),
        ("data-pipeline",     "P2", [12.0]),
        ("reporting-service", "P1", [24.0, 18.0, 36.0]),   # slow MTTR!
        ("legacy-billing",    "P1", [48.0, 72.0]),           # very slow!
        ("legacy-billing",    "P2", [24.0, 30.0]),
        ("auth-service",      "P2", [2.0]),
        ("mobile-app",        "P2", [5.0, 8.0]),
    ]

    for repo_name, severity, ttrs in incident_config:
        for ttr_hrs in ttrs:
            offset_hrs = random.randint(24, 90 * 24)
            started_at = now - timedelta(hours=offset_hrs)
            resolved_at = started_at + timedelta(hours=ttr_hrs)
            incidents.append({
                "id": f"gh-inc-{inc_id:04d}",
                "repo_name": repo_name,
                "severity": severity,
                "title": f"{severity} incident in {repo_name}",
                "started_at": started_at.isoformat() + "Z",
                "resolved_at": resolved_at.isoformat() + "Z",
                "ttr_hours": ttr_hrs,
                "postmortem_written": random.random() > 0.4,
            })
            inc_id += 1

    return incidents


# Pre-generate data at module load (fixed seed for reproducibility)
random.seed(42)
_MOCK_PRS = _generate_prs()
_MOCK_DEPLOYMENTS = _generate_deployments()
_MOCK_INCIDENTS = _generate_incidents()
random.seed()  # reset seed


_ENTITY_DATA: dict[str, list[dict]] = {
    "repository":   _MOCK_REPOS,
    "pull_request": _MOCK_PRS,
    "deployment":   _MOCK_DEPLOYMENTS,
    "incident":     _MOCK_INCIDENTS,
}


class GitHubMockConnector(ConnectorBase):
    """Mock GitHub connector with realistic engineering velocity data."""

    CONNECTOR_ID = "github"
    DISPLAY_NAME = "GitHub"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 10.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="repository",
                display_name="GitHub Repositories",
                supports_incremental=False,
                estimated_record_count=len(_MOCK_REPOS),
                fields=["id", "name", "full_name", "language", "pushed_at", "open_issues_count"],
            ),
            EntitySchema(
                entity_type="pull_request",
                display_name="Pull Requests",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_PRS),
                fields=["id", "number", "repo_name", "state", "author", "created_at", "merged_at", "cycle_time_hours"],
            ),
            EntitySchema(
                entity_type="deployment",
                display_name="Deployments",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_DEPLOYMENTS),
                fields=["id", "repo_name", "environment", "status", "created_at"],
            ),
            EntitySchema(
                entity_type="incident",
                display_name="Production Incidents",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_INCIDENTS),
                fields=["id", "repo_name", "severity", "started_at", "resolved_at", "ttr_hours"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"GitHub connector does not support entity_type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=str(raw["id"]),
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=raw.get("name") or raw.get("repo_name") or raw.get("title"),
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        records = _ENTITY_DATA.get(entity_type, [])
        since = cursor.last_extracted_at

        def _generate() -> Iterator[RawRecord]:
            for raw in records:
                ts_str = raw.get("created_at") or raw.get("pushed_at") or ""
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.replace(tzinfo=None) <= since:
                        continue
                except (ValueError, TypeError):
                    pass
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=str(raw["id"]),
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=raw.get("name") or raw.get("repo_name"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=38.0,
        )
