"""
scout/workers/github_velocity.py — GitHub Engineering Velocity Worker (Sprint 57)

Complements DORAMetricsWorker with team-level velocity health signals:
  - PR cycle time (time from PR open → merge, per repo)
  - Review lag (time from PR open → first review)
  - Stale PRs (open PRs with no activity for N days)
  - Repository inactivity (repos not pushed in N days)
  - Bus-factor risk (single contributor dominance)

Why this matters for PE:
  - PR cycle time is the #1 bottleneck signal in engineering orgs
  - Stale PRs accumulate merge debt and kill team morale
  - Bus-factor risk means the repo dies if one person leaves
  - Inactive repos often hide unmaintained dependencies and security debt

These findings translate directly to human recommendations:
  "Your payment team has a median 5-day PR review lag —
   that's a process problem, not a people problem."
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class GitHubVelocityWorker(WorkerBase):
    """
    Analyses GitHub PR and repository data to surface engineering velocity
    bottlenecks, stale code debt, and bus-factor concentration risks.
    """

    WORKER_NAME = "GitHubVelocityWorker"

    def run(
        self,
        tenant_id: str,
        config: dict | None = None,
        db: "Session | None" = None,
    ) -> WorkerResult:
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME, config)
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)

        if not cfg.enabled:
            result.findings.append(Finding(
                
                
                title="GitHubVelocityWorker disabled",
                detail="Worker is disabled for this tenant.",
                severity=Severity.LOW,
                
            ))
            return result

        prs = self._get_pull_requests(tenant_id)
        repos = self._get_repositories(tenant_id)

        if not prs and not repos:
            result.findings.append(Finding(
                
                
                title="No GitHub data available",
                detail=(
                    "No pull request or repository data found. "
                    "Connect the GitHub connector to enable velocity analysis."
                ),
                severity=Severity.MEDIUM,
                
            ))
            return result

        # ── Run all velocity checks ──────────────────────────────────────────
        if prs:
            self._check_pr_cycle_time(result, tenant_id, cfg, prs)
            self._check_review_lag(result, tenant_id, cfg, prs)
            self._check_stale_prs(result, tenant_id, cfg, prs)

        if repos:
            self._check_inactive_repos(result, tenant_id, cfg, repos)

        if prs:
            self._check_bus_factor(result, tenant_id, cfg, prs)

        return result

    # ─────────────────────────────────────────────────────
    # DATA RETRIEVAL
    # ─────────────────────────────────────────────────────

    def _get_pull_requests(self, tenant_id: str) -> list[dict]:
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (pr:PullRequest {tenant_id: $tenant_id})
                    RETURN pr.id as id, pr.repo_name as repo_name,
                           pr.state as state, pr.author as author,
                           pr.created_at as created_at,
                           pr.merged_at as merged_at,
                           pr.first_review_at as first_review_at,
                           pr.cycle_time_hours as cycle_time_hours,
                           pr.review_lag_hours as review_lag_hours,
                           pr.additions as additions, pr.deletions as deletions
                    ORDER BY pr.created_at DESC
                    LIMIT 3000
                    """,
                    tenant_id=tenant_id,
                )
                rows = [dict(r) for r in result]
                if rows:
                    return rows
        except Exception:
            pass
        return self._mock_prs()

    def _get_repositories(self, tenant_id: str) -> list[dict]:
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (r:Repository {tenant_id: $tenant_id})
                    RETURN r.id as id, r.name as name, r.full_name as full_name,
                           r.pushed_at as pushed_at,
                           r.primary_owner as primary_owner, r.team as team,
                           r.open_issues_count as open_issues_count
                    """,
                    tenant_id=tenant_id,
                )
                rows = [dict(r) for r in result]
                if rows:
                    return rows
        except Exception:
            pass
        return self._mock_repos()

    def _mock_prs(self) -> list[dict]:
        try:
            from scout.connectors.mock.github import _MOCK_PRS
            return _MOCK_PRS
        except ImportError:
            return []

    def _mock_repos(self) -> list[dict]:
        try:
            from scout.connectors.mock.github import _MOCK_REPOS
            return _MOCK_REPOS
        except ImportError:
            return []

    # ─────────────────────────────────────────────────────
    # VELOCITY CHECKS
    # ─────────────────────────────────────────────────────

    def _check_pr_cycle_time(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        prs: list[dict],
    ) -> None:
        """Flag repos where median merged-PR cycle time exceeds thresholds."""
        critical_hrs = cfg.get("pr_cycle_critical_hrs")
        high_hrs = cfg.get("pr_cycle_high_hrs")
        medium_hrs = cfg.get("pr_cycle_medium_hrs")

        merged_by_repo: dict[str, list[float]] = defaultdict(list)
        for pr in prs:
            if pr.get("state") == "merged" and pr.get("cycle_time_hours") is not None:
                merged_by_repo[pr["repo_name"]].append(float(pr["cycle_time_hours"]))

        for repo_name, cycle_times in merged_by_repo.items():
            if len(cycle_times) < 3:
                continue  # Not enough data
            median_hrs = statistics.median(cycle_times)

            if median_hrs > critical_hrs:
                severity = Severity.CRITICAL
            elif median_hrs > high_hrs:
                severity = Severity.HIGH
            elif median_hrs > medium_hrs:
                severity = Severity.MEDIUM
            else:
                continue

            days = median_hrs / 24
            time_label = f"{days:.1f} days" if days >= 1 else f"{median_hrs:.0f} hours"

            result.findings.append(Finding(
                
                
                title=f"Slow PR cycle time: {repo_name} (median {time_label})",
                detail=(
                    f"Median PR cycle time in '{repo_name}' is {time_label} "
                    f"(across {len(cycle_times)} merged PRs). "
                    f"Industry benchmark: <24h for high-performing teams. "
                    f"Slow cycle time indicates large batch sizes, blocked reviews, "
                    f"or excessive rework."
                ),
                severity=severity,
                
                data={
                    "repo_name": repo_name,
                    "median_cycle_hrs": round(median_hrs, 1),
                    "pr_count": len(cycle_times),
                    "p90_cycle_hrs": round(sorted(cycle_times)[int(len(cycle_times) * 0.9)], 1),
                },
                recommended_action=(
                    "Adopt a PR size limit (< 400 lines changed). "
                    "Set a team SLA: all PRs reviewed within 4 hours. "
                    "Use draft PRs for early feedback to reduce review iterations."
                ),
            ))

    def _check_review_lag(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        prs: list[dict],
    ) -> None:
        """Flag repos with slow first-review response time."""
        critical_hrs = cfg.get("review_lag_critical_hrs")
        high_hrs = cfg.get("review_lag_high_hrs")

        lag_by_repo: dict[str, list[float]] = defaultdict(list)
        for pr in prs:
            lag = pr.get("review_lag_hours")
            if lag is not None and pr.get("state") == "merged":
                lag_by_repo[pr["repo_name"]].append(float(lag))

        for repo_name, lags in lag_by_repo.items():
            if len(lags) < 3:
                continue
            median_lag = statistics.median(lags)

            if median_lag > critical_hrs:
                severity = Severity.CRITICAL
            elif median_lag > high_hrs:
                severity = Severity.HIGH
            else:
                continue

            days = median_lag / 24
            lag_label = f"{days:.1f} days" if days >= 1 else f"{median_lag:.0f} hours"

            result.findings.append(Finding(
                
                
                title=f"Slow PR review response: {repo_name} (median {lag_label} to first review)",
                detail=(
                    f"PRs in '{repo_name}' wait a median {lag_label} before receiving "
                    f"their first review (across {len(lags)} merged PRs). "
                    f"This is a team process bottleneck — reviewers are not prioritising reviews "
                    f"or the reviewer pool is too small."
                ),
                severity=severity,
                
                data={
                    "repo_name": repo_name,
                    "median_review_lag_hrs": round(median_lag, 1),
                    "pr_count": len(lags),
                },
                recommended_action=(
                    "Add review assignments to PR templates. "
                    "Create a rotating 'PR sheriff' role. "
                    "Block end-of-day standup on any PR open > 4 hours without a review."
                ),
            ))

    def _check_stale_prs(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        prs: list[dict],
    ) -> None:
        """Flag repos with too many stale open PRs."""
        stale_days = cfg.get("stale_pr_days", 14)
        critical_count = cfg.get("stale_pr_critical_count", 10)
        high_count = cfg.get("stale_pr_high_count", 5)

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=stale_days)

        stale_by_repo: dict[str, list[dict]] = defaultdict(list)
        for pr in prs:
            if pr.get("state") != "open":
                continue
            created_str = pr.get("created_at", "")
            try:
                created = datetime.fromisoformat(created_str.replace("Z", ""))
                if created < cutoff:
                    stale_by_repo[pr["repo_name"]].append(pr)
            except (ValueError, TypeError):
                pass

        for repo_name, stale_prs in stale_by_repo.items():
            count = len(stale_prs)
            if count >= critical_count:
                severity = Severity.CRITICAL
            elif count >= high_count:
                severity = Severity.HIGH
            else:
                continue

            result.findings.append(Finding(
                
                
                title=f"Stale PRs accumulating: {repo_name} ({count} PRs > {stale_days}d old)",
                detail=(
                    f"Repository '{repo_name}' has {count} open pull requests with no activity "
                    f"for more than {stale_days} days. "
                    f"Stale PRs are a sign of incomplete work, blocked reviewers, or "
                    f"abandoned features accumulating as technical debt."
                ),
                severity=severity,
                
                data={
                    "repo_name": repo_name,
                    "stale_pr_count": count,
                    "stale_threshold_days": stale_days,
                    "oldest_pr_created": min(
                        (pr.get("created_at", "") for pr in stale_prs), default=None
                    ),
                },
                recommended_action=(
                    f"Run a 'PR amnesty' sprint to close or merge all stale PRs in '{repo_name}'. "
                    "Adopt a policy: no PR open >7 days without a daily standup mention. "
                    "Close abandoned PRs and document the decision in a ticket."
                ),
            ))

    def _check_inactive_repos(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        repos: list[dict],
    ) -> None:
        """Flag repositories with no recent push activity."""
        inactive_days = cfg.get("repo_inactive_days", 30)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=inactive_days)

        for repo in repos:
            pushed_str = repo.get("pushed_at", "")
            if not pushed_str:
                continue
            try:
                pushed = datetime.fromisoformat(pushed_str.replace("Z", ""))
            except (ValueError, TypeError):
                continue

            if pushed >= cutoff:
                continue

            days_inactive = (datetime.now(timezone.utc).replace(tzinfo=None) - pushed).days
            open_issues = repo.get("open_issues_count", 0) or 0

            severity = Severity.HIGH if days_inactive > inactive_days * 3 else Severity.MEDIUM

            result.findings.append(Finding(
                
                
                title=f"Inactive repository: {repo.get('name', repo.get('repo_name', ''))} ({days_inactive}d)",
                detail=(
                    f"Repository '{repo.get('name', '')}' has had no push activity for {days_inactive} days. "
                    f"It currently has {open_issues} open issues. "
                    f"Inactive repos accumulate unmaintained dependencies, stale secrets, "
                    f"and unpatched security vulnerabilities."
                ),
                severity=severity,
                
                data={
                    "repo_name": repo.get("name", ""),
                    "days_inactive": days_inactive,
                    "open_issues": open_issues,
                    "primary_owner": repo.get("primary_owner"),
                    "team": repo.get("team"),
                    "last_pushed_at": pushed_str,
                },
                recommended_action=(
                    "Audit the repository: is it actively used in production? "
                    "If yes, assign an owner and resume maintenance. "
                    "If no, archive it on GitHub and document the deprecation decision."
                ),
            ))

    def _check_bus_factor(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        prs: list[dict],
    ) -> None:
        """Flag repos where a single contributor dominates commit/PR activity."""
        bus_factor_pct = cfg.get("bus_factor_pct", 0.70)

        # Count PRs merged per author per repo
        author_prs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        repo_totals: dict[str, int] = defaultdict(int)

        for pr in prs:
            if pr.get("state") != "merged":
                continue
            repo = pr.get("repo_name", "")
            author = pr.get("author", "unknown")
            if repo and author:
                author_prs[repo][author] += 1
                repo_totals[repo] += 1

        for repo_name, total in repo_totals.items():
            if total < 5:
                continue  # Not enough data

            top_author = max(author_prs[repo_name], key=author_prs[repo_name].get)
            top_count = author_prs[repo_name][top_author]
            pct = top_count / total

            if pct < bus_factor_pct:
                continue

            result.findings.append(Finding(
                
                
                title=f"Bus-factor risk: {repo_name} ({pct:.0%} single contributor)",
                detail=(
                    f"In repository '{repo_name}', a single contributor ({top_author}) "
                    f"authored {pct:.0%} of all merged PRs ({top_count}/{total}). "
                    f"This creates critical bus-factor risk: if this person leaves, "
                    f"the team loses institutional knowledge of this codebase."
                ),
                severity=Severity.HIGH,
                
                data={
                    "repo_name": repo_name,
                    "top_contributor": top_author,
                    "top_contributor_pct": round(pct, 2),
                    "top_contributor_pr_count": top_count,
                    "total_prs": total,
                    "contributor_breakdown": dict(author_prs[repo_name]),
                },
                recommended_action=(
                    f"Initiate knowledge transfer from {top_author} immediately. "
                    "Pair-program key modules. "
                    "Create detailed architecture documentation for this repository. "
                    "Set a policy: no single contributor owns >50% of any repo."
                ),
            ))
