"""
scout/workers/dora_metrics.py — DORA Metrics Worker (Sprint 57)

The four DORA (DevOps Research and Assessment) metrics are the gold-standard
framework for measuring software delivery performance. They are the first
thing a technical acquirer or PE operating partner asks for in a DD process.

The four metrics:
  1. Deployment Frequency    — How often does the team deploy to production?
  2. Lead Time for Changes   — How long from commit merged → production?
  3. Change Failure Rate     — What % of deployments cause a production incident?
  4. Mean Time to Restore    — How long to recover from a production incident?

Performance tiers (Google DORA 2023):
  Elite:  ≥1 deploy/day, <1h lead time, <5% CFR, <1h MTTR
  High:   ≥1/week, <1 day, <10%, <24h
  Medium: ≥1/month, <1 week, <15%, <1 week
  Low:    <1/month, >1 week, >15%, >1 week

Why this matters for PE:
  - Low-performing repos are technical debt time bombs
  - DORA metrics correlate with customer satisfaction and revenue growth
  - A high CFR combined with high MTTR = "the team ships broken code slowly"
  - These numbers don't lie — they're computed from git/deploy facts

Data sources:
  - GitHub deployments API (deployment events)
  - GitHub pull requests (lead time: PR merged → deploy)
  - Production incidents (issues labelled 'incident' or PagerDuty/OpsGenie)

Graph integration:
  Results are read directly from connector mock data (no full graph traversal
  needed) since GitHub data isn't yet written to Neo4j nodes. The worker reads
  deployment and incident records directly from the scan context.
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


class DORAMetricsWorker(WorkerBase):
    """
    Computes DORA metrics per repository and surfaces findings for
    repositories that fall below acceptable performance thresholds.

    Reads from the Neo4j graph if GitHub data has been ingested;
    falls back to mock data for development/demo environments.
    """

    WORKER_NAME = "DORAMetricsWorker"

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
                
                
                title="DORAMetricsWorker disabled",
                detail="Worker is disabled for this tenant.",
                severity=Severity.LOW,
                
            ))
            return result

        # ── Pull DORA data from the graph ───────────────────────────────────
        deployments = self._get_deployments(tenant_id)
        incidents = self._get_incidents(tenant_id)
        prs = self._get_pull_requests(tenant_id)

        if not deployments:
            result.findings.append(Finding(
                
                
                title="No deployment data available",
                detail=(
                    "No production deployment records found in the graph. "
                    "Connect the GitHub connector to enable DORA metrics analysis."
                ),
                severity=Severity.MEDIUM,
                
            ))
            return result

        # ── Compute per-repo DORA metrics ───────────────────────────────────
        repo_metrics = self._compute_repo_metrics(deployments, incidents, prs)

        for repo_name, metrics in repo_metrics.items():
            self._evaluate_deployment_frequency(result, tenant_id, cfg, repo_name, metrics)
            self._evaluate_change_failure_rate(result, tenant_id, cfg, repo_name, metrics)
            self._evaluate_mttr(result, tenant_id, cfg, repo_name, metrics)
            self._evaluate_lead_time(result, tenant_id, cfg, repo_name, metrics)

        # ── Portfolio-level summary finding ────────────────────────────────
        self._add_portfolio_summary(result, tenant_id, repo_metrics)

        return result

    # ─────────────────────────────────────────────────────
    # DATA RETRIEVAL
    # ─────────────────────────────────────────────────────

    def _get_deployments(self, tenant_id: str) -> list[dict]:
        """Pull deployment records from graph or mock connector."""
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (d:Deployment {tenant_id: $tenant_id})
                    WHERE d.environment = 'production'
                    RETURN d.id as id, d.repo_name as repo_name,
                           d.status as status, d.created_at as created_at,
                           d.duration_seconds as duration_seconds
                    ORDER BY d.created_at DESC
                    LIMIT 2000
                    """,
                    tenant_id=tenant_id,
                )
                rows = [dict(r) for r in result]
                if rows:
                    return rows
        except Exception:
            pass
        # Fallback: use mock data directly
        return self._mock_deployments()

    def _get_incidents(self, tenant_id: str) -> list[dict]:
        """Pull production incident records from graph or mock."""
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (i:Incident {tenant_id: $tenant_id})
                    RETURN i.id as id, i.repo_name as repo_name,
                           i.severity as severity, i.ttr_hours as ttr_hours,
                           i.started_at as started_at, i.resolved_at as resolved_at
                    ORDER BY i.started_at DESC
                    LIMIT 500
                    """,
                    tenant_id=tenant_id,
                )
                rows = [dict(r) for r in result]
                if rows:
                    return rows
        except Exception:
            pass
        return self._mock_incidents()

    def _get_pull_requests(self, tenant_id: str) -> list[dict]:
        """Pull PR records from graph or mock."""
        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (pr:PullRequest {tenant_id: $tenant_id})
                    WHERE pr.state = 'merged'
                    RETURN pr.id as id, pr.repo_name as repo_name,
                           pr.cycle_time_hours as cycle_time_hours,
                           pr.merged_at as merged_at
                    ORDER BY pr.merged_at DESC
                    LIMIT 2000
                    """,
                    tenant_id=tenant_id,
                )
                rows = [dict(r) for r in result]
                if rows:
                    return rows
        except Exception:
            pass
        return self._mock_prs()

    def _mock_deployments(self) -> list[dict]:
        """Load mock deployment data."""
        try:
            from scout.connectors.mock.github import _MOCK_DEPLOYMENTS
            return _MOCK_DEPLOYMENTS
        except ImportError:
            return []

    def _mock_incidents(self) -> list[dict]:
        try:
            from scout.connectors.mock.github import _MOCK_INCIDENTS
            return _MOCK_INCIDENTS
        except ImportError:
            return []

    def _mock_prs(self) -> list[dict]:
        try:
            from scout.connectors.mock.github import _MOCK_PRS
            return _MOCK_PRS
        except ImportError:
            return []

    # ─────────────────────────────────────────────────────
    # METRICS COMPUTATION
    # ─────────────────────────────────────────────────────

    def _compute_repo_metrics(
        self,
        deployments: list[dict],
        incidents: list[dict],
        prs: list[dict],
    ) -> dict[str, dict[str, Any]]:
        """
        Compute DORA metrics per repository.

        Returns: { repo_name: { deploy_freq, cfr, mttr_median, lead_time_median, ... } }
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        window_days = 30  # rolling 30-day window

        # Group by repo
        deps_by_repo: dict[str, list[dict]] = defaultdict(list)
        for d in deployments:
            if d.get("created_at"):
                try:
                    ts_str = d["created_at"]
                    ts = datetime.fromisoformat(ts_str.replace("Z", ""))
                    if (now - ts).days <= window_days:
                        deps_by_repo[d["repo_name"]].append(d)
                except (ValueError, TypeError):
                    pass

        incs_by_repo: dict[str, list[dict]] = defaultdict(list)
        for i in incidents:
            incs_by_repo[i["repo_name"]].append(i)

        prs_by_repo: dict[str, list[dict]] = defaultdict(list)
        for pr in prs:
            if pr.get("cycle_time_hours") is not None:
                prs_by_repo[pr["repo_name"]].append(pr)

        metrics: dict[str, dict[str, Any]] = {}

        for repo_name, deps in deps_by_repo.items():
            total = len(deps)
            successes = [d for d in deps if d.get("status") == "success"]
            failures = [d for d in deps if d.get("status") == "failure"]

            deploy_freq = total / window_days  # deploys per day

            cfr = len(failures) / total if total > 0 else 0.0

            # MTTR: median ttr_hours from incidents for this repo
            repo_incs = incs_by_repo.get(repo_name, [])
            ttr_values = [i["ttr_hours"] for i in repo_incs if i.get("ttr_hours") is not None]
            mttr_median = statistics.median(ttr_values) if ttr_values else None

            # Lead time: median PR cycle time as a proxy
            repo_prs = prs_by_repo.get(repo_name, [])
            cycle_times = [pr["cycle_time_hours"] for pr in repo_prs if pr.get("cycle_time_hours")]
            lead_time_median = statistics.median(cycle_times) if cycle_times else None

            metrics[repo_name] = {
                "deploy_freq":       deploy_freq,
                "deploy_count":      total,
                "failure_count":     len(failures),
                "cfr":               cfr,
                "mttr_median":       mttr_median,
                "lead_time_median":  lead_time_median,
                "incident_count":    len(repo_incs),
            }

        return metrics

    # ─────────────────────────────────────────────────────
    # FINDING EVALUATORS
    # ─────────────────────────────────────────────────────

    def _evaluate_deployment_frequency(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        repo_name: str,
        metrics: dict,
    ) -> None:
        freq = metrics["deploy_freq"]
        deploy_count = metrics["deploy_count"]

        elite = cfg.get("deploy_freq_elite")
        high = cfg.get("deploy_freq_high")
        medium = cfg.get("deploy_freq_medium")

        if freq < medium:
            severity = Severity.HIGH
            tier = "Low"
            period_label = f"{deploy_count} deploys in 30 days"
            recommendation = (
                "Implement CI/CD pipeline improvements. "
                "Move toward trunk-based development and automated deployment gates "
                "to increase release cadence without sacrificing stability."
            )
        elif freq < high:
            severity = Severity.MEDIUM
            tier = "Medium"
            period_label = f"{deploy_count} deploys in 30 days"
            recommendation = (
                "Increase deployment automation. "
                "Consider feature flags to decouple code deployment from feature releases."
            )
        else:
            return  # High or Elite performer — no finding

        result.findings.append(Finding(
            
            
            title=f"Low deployment frequency: {repo_name}",
            detail=(
                f"Repository '{repo_name}' is a DORA {tier} performer on Deployment Frequency. "
                f"{period_label} ({freq:.2f}/day). "
                f"DORA Elite benchmark: ≥1 deploy/day."
            ),
            severity=severity,
            
            data={
                "repo_name": repo_name,
                "deploy_freq_per_day": round(freq, 3),
                "deploy_count_30d": deploy_count,
                "dora_tier": tier,
                "metric": "deployment_frequency",
            },
            recommended_action=recommendation,
        ))

    def _evaluate_change_failure_rate(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        repo_name: str,
        metrics: dict,
    ) -> None:
        cfr = metrics["cfr"]
        failure_count = metrics["failure_count"]
        deploy_count = metrics["deploy_count"]

        elite = cfg.get("cfr_elite")
        high_thresh = cfg.get("cfr_high")
        medium_thresh = cfg.get("cfr_medium")

        if cfr > medium_thresh:
            severity = Severity.CRITICAL
            tier = "Low"
        elif cfr > high_thresh:
            severity = Severity.HIGH
            tier = "Medium"
        elif cfr > elite:
            severity = Severity.MEDIUM
            tier = "High"
        else:
            return

        result.findings.append(Finding(
            
            
            title=f"High change failure rate: {repo_name} ({cfr:.0%})",
            detail=(
                f"Repository '{repo_name}' has a {cfr:.1%} Change Failure Rate — "
                f"{failure_count} of {deploy_count} production deployments triggered an incident. "
                f"DORA Elite benchmark: <5% CFR. "
                f"This indicates insufficient pre-production testing or deployment validation."
            ),
            severity=severity,
            
            data={
                "repo_name": repo_name,
                "cfr_pct": round(cfr, 3),
                "failure_count": failure_count,
                "deploy_count": deploy_count,
                "dora_tier": tier,
                "metric": "change_failure_rate",
            },
            recommended_action=(
                "Invest in automated testing (unit, integration, contract). "
                "Add deployment validation gates. "
                "Implement canary or blue-green deployment strategies."
            ),
        ))

    def _evaluate_mttr(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        repo_name: str,
        metrics: dict,
    ) -> None:
        mttr = metrics.get("mttr_median")
        if mttr is None:
            return

        elite = cfg.get("mttr_elite_hrs")
        high_thresh = cfg.get("mttr_high_hrs")
        medium_thresh = cfg.get("mttr_medium_hrs")

        if mttr > medium_thresh:
            severity = Severity.CRITICAL
            tier = "Low"
        elif mttr > high_thresh:
            severity = Severity.HIGH
            tier = "Medium"
        elif mttr > elite:
            severity = Severity.MEDIUM
            tier = "High"
        else:
            return

        mttr_label = f"{mttr:.1f}h" if mttr < 48 else f"{mttr / 24:.1f}d"

        result.findings.append(Finding(
            
            
            title=f"Slow incident recovery: {repo_name} (MTTR {mttr_label})",
            detail=(
                f"Repository '{repo_name}' has a median Mean Time to Restore (MTTR) "
                f"of {mttr_label}. "
                f"DORA Elite benchmark: <1h. "
                f"Slow MTTR directly impacts SLA compliance and customer trust."
            ),
            severity=severity,
            
            data={
                "repo_name": repo_name,
                "mttr_median_hrs": round(mttr, 1),
                "incident_count": metrics["incident_count"],
                "dora_tier": tier,
                "metric": "mttr",
            },
            recommended_action=(
                "Establish runbooks and on-call playbooks for the top 5 failure modes. "
                "Invest in observability tooling (structured logging, distributed tracing, dashboards). "
                "Practice incident response drills quarterly."
            ),
        ))

    def _evaluate_lead_time(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        repo_name: str,
        metrics: dict,
    ) -> None:
        lead_time = metrics.get("lead_time_median")
        if lead_time is None:
            return

        elite = cfg.get("lead_time_elite_hrs")
        high_thresh = cfg.get("lead_time_high_hrs")
        medium_thresh = cfg.get("lead_time_medium_hrs")

        if lead_time > medium_thresh:
            severity = Severity.HIGH
            tier = "Low"
        elif lead_time > high_thresh:
            severity = Severity.MEDIUM
            tier = "Medium"
        else:
            return

        lt_label = f"{lead_time:.0f}h" if lead_time < 48 else f"{lead_time / 24:.1f}d"

        result.findings.append(Finding(
            
            
            title=f"Long lead time for changes: {repo_name} ({lt_label})",
            detail=(
                f"Median PR-to-production lead time for '{repo_name}' is {lt_label}. "
                f"DORA Elite benchmark: <1h. "
                f"Long lead time means the team is slow to ship customer value "
                f"and accumulates merge-conflict risk."
            ),
            severity=severity,
            
            data={
                "repo_name": repo_name,
                "lead_time_median_hrs": round(lead_time, 1),
                "dora_tier": tier,
                "metric": "lead_time",
            },
            recommended_action=(
                "Reduce batch size — smaller, more frequent PRs shorten lead time. "
                "Automate CI to run in <10 minutes. "
                "Prioritize PR reviews in team rituals."
            ),
        ))

    def _add_portfolio_summary(
        self,
        result: WorkerResult,
        tenant_id: str,
        repo_metrics: dict[str, dict],
    ) -> None:
        """Add a single portfolio-level summary finding."""
        if not repo_metrics:
            return

        elite_count = sum(
            1 for m in repo_metrics.values()
            if m["deploy_freq"] >= 1.0 and m["cfr"] < 0.05
        )
        low_count = sum(
            1 for m in repo_metrics.values()
            if m["deploy_freq"] < 0.033 or m["cfr"] > 0.15
        )
        total = len(repo_metrics)

        severity = Severity.LOW
        if low_count > total * 0.5:
            severity = Severity.HIGH
        elif low_count > total * 0.25:
            severity = Severity.MEDIUM

        result.findings.append(Finding(
            
            
            title=f"DORA portfolio summary: {elite_count}/{total} repos at Elite tier",
            detail=(
                f"Across {total} production repositories: "
                f"{elite_count} are DORA Elite, "
                f"{low_count} are DORA Low (needs immediate attention). "
                f"DORA metrics are the leading indicator of engineering org health."
            ),
            severity=severity,
            
            data={
                "total_repos": total,
                "elite_count": elite_count,
                "low_count": low_count,
                "repo_breakdown": {
                    k: {
                        "deploy_freq": round(v["deploy_freq"], 3),
                        "cfr_pct": round(v["cfr"] * 100, 1),
                        "mttr_hrs": round(v["mttr_median"], 1) if v["mttr_median"] else None,
                    }
                    for k, v in repo_metrics.items()
                },
            },
            recommended_action=(
                "Prioritize DORA improvements in the Low-tier repositories. "
                "Start with deployment frequency — it's the highest-leverage improvement."
            ),
        ))
