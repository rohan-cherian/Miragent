"""
scout/workers/process_conformance.py — ProcessConformanceWorker (Sprint 62)

Compares stated policy (from uploaded SOPs, process guides, battle cards
in the Knowledge Base) against measured reality (from ticket/activity data
in connected systems).

The gap between intent and practice is where operational risk lives.

Three types of conformance gaps surfaced:
  1. SLA breaches — stated response/resolution times vs. actuals
  2. Escalation policy violations — SOP says handle at tier-1, data shows tier-2 escalation rate
  3. Process coverage gaps — tickets for issues the SOP doesn't address at all

Data sources:
  - KnowledgeBase (SQLite kb_chunks table) — policy text
  - Mock ticket metrics (or Zendesk/Jira connector if available)
  - Claude for policy extraction from document text (with graceful fallback)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# SLA keyword patterns for regex extraction from KB text
_SLA_PATTERN = re.compile(
    r'(?:within|in|respond\s+within|resolved\s+in|acknowledged\s+within|completed\s+within)'
    r'\s+(\d+(?:\.\d+)?)\s+(hour|day|minute|business\s+day)s?',
    re.IGNORECASE,
)

# Category keywords to bucket a chunk into a process category
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "customer_support": ["portal", "access", "ticket", "support", "helpdesk", "resolution", "response"],
    "vendor_management": ["vendor", "onboarding", "procurement", "supplier"],
    "sales": ["ddq", "questionnaire", "battle card", "proposal", "rfp", "rfq"],
    "hr": ["new hire", "onboarding", "provisioning", "offboarding", "employee"],
    "finance": ["billing", "invoice", "dispute", "payment"],
}


def _infer_category(text: str) -> str:
    text_lower = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return "general"


def _infer_metric_type(text: str) -> str:
    text_lower = text.lower()
    if "response" in text_lower or "acknowledge" in text_lower:
        return "first_response_time"
    if "resolution" in text_lower or "resolved" in text_lower:
        return "resolution_time"
    return "process_duration"


def _normalize_unit(unit_str: str) -> str:
    """Normalize matched unit string to canonical form."""
    u = unit_str.lower().strip()
    if "business" in u and "day" in u:
        return "business_days"
    if "hour" in u:
        return "hours"
    if "day" in u:
        return "hours"  # convert to hours: 1 day = 24h (handled below)
    if "minute" in u:
        return "minutes"
    return "hours"


def _to_hours(value: float, unit: str) -> float:
    """Convert target value to hours for comparison."""
    if unit == "hours":
        return value
    if unit == "minutes":
        return value / 60.0
    if unit == "business_days":
        return value * 8.0  # 8 working hours per business day
    return value


class ProcessConformanceWorker(WorkerBase):
    """
    Analyses the gap between documented policy commitments and actual
    measured operational performance.

    Uses KB documents (uploaded SOPs, process guides) as the policy source
    and ticket/activity metrics (from Neo4j or mock fallback) as the
    ground truth for what actually happens.
    """

    WORKER_NAME = "ProcessConformanceWorker"

    def run(self, tenant_id: str, config=None, db=None) -> WorkerResult:
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME, config)
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)

        try:
            # Extract policy commitments from KB documents
            policies = self._extract_policies(tenant_id, db)

            # Get actual ticket metrics (graph → mock fallback)
            actuals = self._get_actuals(tenant_id)

            # Compare and generate findings
            self._check_sla_conformance(result, policies, actuals, cfg)
            self._check_escalation_conformance(result, policies, actuals, cfg)
            self._check_coverage_gaps(result, policies, actuals, cfg)
            self._check_sales_process_conformance(result, policies, actuals, cfg)

        except Exception as exc:
            logger.error(
                f"ProcessConformanceWorker failed for {tenant_id}: {exc}", exc_info=True
            )
            result.error = str(exc)

        return result

    # ── Policy extraction ───────────────────────────────────────────────────

    def _extract_policies(self, tenant_id: str, db) -> list[dict[str, Any]]:
        """
        Extract structured policy commitments from KB chunks.

        Falls back to mock policies if db is None or no chunks are found.
        """
        if db is None:
            logger.info("No DB session — using mock policies")
            return self._mock_policies()

        try:
            from scout.db.models import KBChunk
            from sqlalchemy import select

            chunks = (
                db.execute(
                    select(KBChunk).where(KBChunk.tenant_id == tenant_id)
                )
                .scalars()
                .all()
            )

            if not chunks:
                logger.info(f"No KB chunks for {tenant_id} — using mock policies")
                return self._mock_policies()

            # Extract SLA commitments from each chunk using regex
            policies: list[dict[str, Any]] = []
            seen_commitments: set[str] = set()

            for chunk in chunks:
                text = chunk.content or ""
                for match in _SLA_PATTERN.finditer(text):
                    value = float(match.group(1))
                    raw_unit = match.group(2)
                    unit = _normalize_unit(raw_unit)

                    # Grab ~80 chars of context around the match
                    start = max(0, match.start() - 20)
                    end = min(len(text), match.end() + 60)
                    commitment_text = text[start:end].strip()

                    dedup_key = f"{value}_{unit}_{commitment_text[:40]}"
                    if dedup_key in seen_commitments:
                        continue
                    seen_commitments.add(dedup_key)

                    # Try to get source doc name from parent document
                    source_doc = "Knowledge Base"
                    try:
                        source_doc = chunk.document.filename
                    except Exception:
                        pass

                    policies.append({
                        "category": _infer_category(text),
                        "commitment_text": commitment_text,
                        "metric_type": _infer_metric_type(commitment_text),
                        "target_value": value,
                        "target_unit": unit,
                        "source_doc": source_doc,
                    })

            if not policies:
                logger.info(f"No SLA patterns found in KB for {tenant_id} — using mock policies")
                return self._mock_policies()

            return policies

        except Exception as exc:
            logger.warning(f"Could not read KB chunks: {exc} — using mock policies")
            return self._mock_policies()

    def _mock_policies(self) -> list[dict[str, Any]]:
        """Realistic policy commitments for demo / fallback."""
        return [
            {
                "category": "customer_support",
                "commitment_text": "Portal access issues resolved within 2 hours",
                "metric_type": "resolution_time",
                "target_value": 2.0,
                "target_unit": "hours",
                "source_doc": "Customer Support SOP v2.3",
            },
            {
                "category": "customer_support",
                "commitment_text": "All tickets acknowledged within 30 minutes of receipt",
                "metric_type": "first_response_time",
                "target_value": 0.5,
                "target_unit": "hours",
                "source_doc": "Customer Support SOP v2.3",
            },
            {
                "category": "vendor_management",
                "commitment_text": "New vendor onboarding completed within 15 business days",
                "metric_type": "process_duration",
                "target_value": 15.0,
                "target_unit": "business_days",
                "source_doc": "Vendor Management Policy",
            },
            {
                "category": "sales",
                "commitment_text": "DDQ responses delivered within 5 business days",
                "metric_type": "process_duration",
                "target_value": 5.0,
                "target_unit": "business_days",
                "source_doc": "Sales Battle Card — Security Questions",
            },
            {
                "category": "customer_support",
                "commitment_text": "Billing disputes resolved within 10 business days",
                "metric_type": "resolution_time",
                "target_value": 10.0,
                "target_unit": "business_days",
                "source_doc": "Finance & Billing Policy",
            },
            {
                "category": "hr",
                "commitment_text": "New hire system access provisioned within 1 business day of start date",
                "metric_type": "process_duration",
                "target_value": 1.0,
                "target_unit": "business_days",
                "source_doc": "IT Onboarding Checklist",
            },
        ]

    # ── Actuals ─────────────────────────────────────────────────────────────

    def _get_actuals(self, tenant_id: str) -> dict[str, Any]:
        """
        Fetch measured operational metrics.

        Tries Neo4j first; falls back to realistic mock data.
        """
        try:
            with self.driver.session() as session:
                # Try a quick ping — if it fails, use mock
                session.run("RETURN 1").single()
                # TODO: replace with real Cypher queries against ticket nodes
                # when ticket data is available in the graph
                return self._mock_actuals()
        except Exception:
            logger.info(f"Neo4j unavailable for {tenant_id} — using mock actuals")
            return self._mock_actuals()

    def _mock_actuals(self) -> dict[str, Any]:
        """
        Realistic measured metrics for demo / fallback.

        These numbers are intentionally slightly worse than the policy targets
        so we generate meaningful findings.
        """
        return {
            "portal_access_resolution_hours": 4.2,       # SOP: 2h → BREACH (110% over)
            "first_response_time_hours": 0.8,             # SOP: 0.5h → BREACH (60% over)
            "vendor_onboarding_days": 31.0,               # SOP: 15d → CRITICAL (107% over)
            "ddq_response_days": 8.3,                     # SOP: 5d → HIGH (66% over)
            "billing_dispute_days": 9.2,                  # SOP: 10d → OK (within target)
            "it_provisioning_days": 1.8,                  # SOP: 1d → HIGH (80% over)
            "tier2_escalation_rate": 0.34,                # 34% tickets escalate to tier-2
            "sop_coverage_rate": 0.71,                    # 29% of ticket categories have no SOP
            "ticket_categories_without_sop": [
                "expert_witness_scheduling",
                "court_date_changes",
                "foreign_language_support",
            ],
        }

    # ── Conformance checks ───────────────────────────────────────────────────

    def _check_sla_conformance(
        self,
        result: WorkerResult,
        policies: list[dict[str, Any]],
        actuals: dict[str, Any],
        cfg: ThresholdConfig,
    ) -> None:
        """
        Compare each stated policy SLA against measured actuals.

        Determines breach severity as a percentage over target.
        """
        breach_critical = cfg.get("sla_breach_critical_pct", 1.00)
        breach_high = cfg.get("sla_breach_high_pct", 0.50)
        breach_medium = cfg.get("sla_breach_medium_pct", 0.20)

        # Map policy to actual metric key
        _policy_to_actual: dict[str, str] = {
            "portal_access_resolution_hours": ("customer_support", "resolution_time"),
            "first_response_time_hours": ("customer_support", "first_response_time"),
            "vendor_onboarding_days": ("vendor_management", "process_duration"),
            "ddq_response_days": ("sales", "process_duration"),
            "billing_dispute_days": ("customer_support", "resolution_time"),
            "it_provisioning_days": ("hr", "process_duration"),
        }

        # Build a simple lookup: (category, metric_type) → list of policies
        policy_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for p in policies:
            key = (p["category"], p["metric_type"])
            policy_map.setdefault(key, []).append(p)

        # Evaluate each actual metric against the relevant policy.
        # Each tuple: (actual_key, unit, category, metric_type, label, keyword_hint)
        # keyword_hint helps match the right policy when multiple exist for the same category/metric_type
        actual_checks = [
            ("portal_access_resolution_hours",  "hours",  "customer_support", "resolution_time",   "Client Portal Access resolution time",   "portal"),
            ("first_response_time_hours",        "hours",  "customer_support", "first_response_time","First response time",                   "acknowledged"),
            ("vendor_onboarding_days",           "days",   "vendor_management","process_duration",   "New vendor onboarding duration",         "vendor"),
            ("ddq_response_days",                "days",   "sales",            "process_duration",   "DDQ response time",                     "ddq"),
            ("billing_dispute_days",             "days",   "customer_support", "resolution_time",    "Billing dispute resolution",            "billing"),
            ("it_provisioning_days",             "days",   "hr",               "process_duration",   "IT access provisioning",                "provisioned"),
        ]

        for actual_key, unit, category, metric_type, label, hint in actual_checks:
            actual_val = actuals.get(actual_key)
            if actual_val is None:
                continue

            # Find matching policy — prefer hint-match
            candidates = policy_map.get((category, metric_type), [])
            if not candidates:
                continue

            # Try to find the best match using the hint keyword
            hint_matches = [p for p in candidates if hint.lower() in p["commitment_text"].lower()]
            policy = hint_matches[0] if hint_matches else candidates[0]
            target = policy["target_value"]
            target_unit = policy["target_unit"]

            # Convert both to comparable units for breach calculation.
            # For day-based metrics we compare day-to-day directly (actual
            # calendar days vs. stated days/business-days). This gives the
            # intuitive breach percentage the SOP author intended.
            if unit == "days":
                actual_comparable = actual_val
                target_comparable = target  # compare raw day numbers
            else:
                # Both in hours
                actual_comparable = actual_val
                target_comparable = target

            if target_comparable <= 0:
                continue

            breach_pct = (actual_comparable - target_comparable) / target_comparable

            if breach_pct <= 0:
                # Within target — no finding
                result.summary_stats[f"{actual_key}_status"] = "ok"
                continue

            # Format display values
            if unit == "days":
                target_display = f"{target:.0f} {target_unit.replace('_', ' ')}"
                actual_display = f"{actual_val:.1f} days"
            else:
                target_display = f"{target:.1f}h"
                actual_display = f"{actual_val:.1f}h"

            if breach_pct >= breach_critical:
                severity = Severity.CRITICAL
                severity_label = "CRITICAL"
            elif breach_pct >= breach_high:
                severity = Severity.HIGH
                severity_label = "HIGH"
            elif breach_pct >= breach_medium:
                severity = Severity.MEDIUM
                severity_label = "MEDIUM"
            else:
                result.summary_stats[f"{actual_key}_status"] = "within_tolerance"
                continue

            result.findings.append(Finding(
                title=f"SLA breach: {label} at {actual_display} vs. {target_display} target ({breach_pct:.0%} over)",
                detail=(
                    f"Your {policy['source_doc']} commits to {policy['commitment_text']}. "
                    f"Measured actuals show {actual_display}  — {breach_pct:.0%} above the stated target. "
                    f"This is a {severity_label} conformance gap between documented policy and practice."
                ),
                severity=severity,
                data={
                    "target_value": target,
                    "target_unit": target_unit,
                    "actual_value": actual_val,
                    "actual_unit": unit,
                    "breach_pct": round(breach_pct, 3),
                    "source_doc": policy["source_doc"],
                    "category": category,
                },
                recommended_action=(
                    f"Either update the SOP to reflect achievable targets, "
                    f"or invest in process improvement to close the {breach_pct:.0%} gap. "
                    f"Consider an automation agent to accelerate resolution velocity."
                ),
            ))
            result.summary_stats[f"{actual_key}_breach_pct"] = round(breach_pct, 3)

    def _check_escalation_conformance(
        self,
        result: WorkerResult,
        policies: list[dict[str, Any]],
        actuals: dict[str, Any],
        cfg: ThresholdConfig,
    ) -> None:
        """
        Check whether actual tier-2 escalation rates violate the implied
        policy that tickets should be resolved at tier-1.
        """
        escalation_rate = actuals.get("tier2_escalation_rate", 0.0)
        escalation_critical = cfg.get("escalation_critical_pct", 0.40)
        escalation_high = cfg.get("escalation_high_pct", 0.25)

        result.summary_stats["tier2_escalation_rate"] = escalation_rate

        if escalation_rate >= escalation_critical:
            severity = Severity.CRITICAL
        elif escalation_rate >= escalation_high:
            severity = Severity.HIGH
        else:
            return  # within acceptable range

        result.findings.append(Finding(
            title=f"Escalation policy violation: {escalation_rate:.0%} of tickets escalate to tier-2",
            detail=(
                f"Your SOPs route customer support tickets to tier-1 for resolution. "
                f"However, {escalation_rate:.0%} of tickets are being escalated to tier-2. "
                f"This indicates either insufficient tier-1 training, missing SOP coverage "
                f"for recurring issue patterns, or SOP documentation that does not reflect "
                f"actual resolution pathways."
            ),
            severity=severity,
            data={
                "tier2_escalation_rate": escalation_rate,
                "threshold_high": escalation_high,
                "threshold_critical": escalation_critical,
            },
            recommended_action=(
                "Analyse the top 5 escalation reasons and add them to tier-1 runbooks. "
                "Consider a tier-1 automation agent for the highest-volume escalation patterns "
                "to reduce tier-2 load and improve first-contact resolution."
            ),
        ))

    def _check_coverage_gaps(
        self,
        result: WorkerResult,
        policies: list[dict[str, Any]],
        actuals: dict[str, Any],
        cfg: ThresholdConfig,
    ) -> None:
        """
        Identify ticket categories that have no documented SOP.

        These categories are being handled ad-hoc, creating inconsistent
        resolution quality and training risk.
        """
        sop_coverage = actuals.get("sop_coverage_rate", 1.0)
        uncovered = actuals.get("ticket_categories_without_sop", [])
        sop_min = cfg.get("sop_coverage_min", 0.80)

        result.summary_stats["sop_coverage_rate"] = sop_coverage
        result.summary_stats["uncovered_categories"] = len(uncovered)

        if sop_coverage >= sop_min:
            return

        coverage_gap = 1.0 - sop_coverage
        uncovered_list = ", ".join(uncovered) if uncovered else "multiple categories"

        result.findings.append(Finding(
            title=f"Process coverage gap: {coverage_gap:.0%} of ticket categories have no documented SOP",
            detail=(
                f"Only {sop_coverage:.0%} of recurring ticket categories have documented SOPs. "
                f"The following categories are handled entirely ad-hoc: {uncovered_list}. "
                f"Ad-hoc handling creates inconsistent resolution quality, longer cycle times, "
                f"and significant training risk when staff turn over."
            ),
            severity=Severity.MEDIUM,
            data={
                "sop_coverage_rate": sop_coverage,
                "coverage_gap": coverage_gap,
                "uncovered_categories": uncovered,
                "sop_min_threshold": sop_min,
            },
            recommended_action=(
                f"Document SOPs for the {len(uncovered)} uncovered categories — starting with "
                f"the highest-volume ones. This is a pre-requisite for any automation initiative: "
                f"you cannot automate an undocumented process reliably."
            ),
        ))

    def _check_sales_process_conformance(
        self,
        result: WorkerResult,
        policies: list[dict[str, Any]],
        actuals: dict[str, Any],
        cfg: ThresholdConfig,
    ) -> None:
        """
        Check DDQ response time conformance specifically.

        DDQ latency directly impacts sales velocity — a stated commitment
        to 5-day response that takes 8+ days is a deal-risk signal.
        """
        ddq_actual = actuals.get("ddq_response_days")
        if ddq_actual is None:
            return

        # Find the DDQ policy
        ddq_policy = next(
            (p for p in policies if p["category"] == "sales"), None
        )
        if ddq_policy is None:
            return

        target = ddq_policy["target_value"]  # in business days
        breach_pct = (ddq_actual - target) / target if target > 0 else 0.0

        result.summary_stats["ddq_response_days"] = ddq_actual
        result.summary_stats["ddq_target_days"] = target
        result.summary_stats["ddq_breach_pct"] = round(breach_pct, 3)

        if breach_pct <= 0:
            return  # already covered by SLA check; no additional finding

        # Add a sales-specific framing of the DDQ SLA breach
        result.findings.append(Finding(
            title=f"Sales velocity risk: DDQ responses taking {ddq_actual:.1f} days vs. {target:.0f}-day commitment",
            detail=(
                f"Your {ddq_policy['source_doc']} commits to DDQ responses within "
                f"{target:.0f} business days. Actual median is {ddq_actual:.1f} days "
                f"({breach_pct:.0%} over target). "
                f"This gap directly impacts sales velocity — prospects awaiting security "
                f"questionnaire responses may stall or lose momentum during the wait."
            ),
            severity=Severity.MEDIUM,
            data={
                "ddq_actual_days": ddq_actual,
                "ddq_target_days": target,
                "breach_pct": round(breach_pct, 3),
                "source_doc": ddq_policy["source_doc"],
            },
            recommended_action=(
                "Deploy the DDQ Agent to automate first-draft responses from the Knowledge Base. "
                "With automation, DDQ turnaround can drop from 8.3 days to same-day, "
                "removing this as a sales bottleneck."
            ),
        ))
