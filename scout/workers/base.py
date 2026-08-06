"""
scout/workers/base.py — Abstract base class for all Intelligence Workers.

What is a Worker?
  A Worker reads the digital twin (Neo4j graph), runs analytical logic,
  and returns structured findings — a list of observations with severity
  ratings, supporting data, and recommended actions.

  Workers do NOT write to the graph. They are read-only analysts.
  They do NOT call external APIs. All the data they need is already in Neo4j.

Why an ABC (Abstract Base Class)?
  Same reason as ConnectorBase — it's a contract. Every Worker must
  implement run() and return a WorkerResult. This makes the AI Analyst
  layer simple: it calls worker.run() on each worker without knowing
  the details of how any specific worker operates.

  "Program to an interface, not an implementation." — Design Patterns (GoF)

The worker hierarchy:
  WorkerBase (ABC)
    ├── WorkforceWorker    — org health, span of control, attrition risk
    └── VendorWorker       — spend risk, renewal urgency, consolidation
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext


class Severity(str, Enum):
    """
    How urgent is this finding?

    CRITICAL  → Act this week (renewal in 14 days, CISO left the company)
    HIGH      → Act this month (3 managers overloaded, $500k contract up for renewal)
    MEDIUM    → Act this quarter (span of control drift, duplicate vendor category)
    LOW       → Monitor (minor inefficiency, one data quality issue)
    INFO      → Context (background fact with no action required)
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Finding:
    """
    One analytical observation from a Worker.

    A Finding has:
      - title: a short headline (fits in one line of a slide)
      - detail: the full explanation (1-3 sentences, citing specific entities)
      - severity: how urgent is this
      - data: the raw numbers behind the finding (for the AI to cite)
      - recommended_action: what should the CIO/PE partner do about it
        (entity-specific: names the actual deal, person, or account)
      - confidence: how reliable is this finding given data quality
        ("high" | "medium" | "low" | "uncertain")
      - specific_entities: the exact people, deals, or accounts this
        finding is about — enables entity-level drill-down in the UI
        Format: [{"type": "deal", "name": "...", "id": "...", ...}, ...]
      - context_note: optional note explaining any caveats (e.g., data
        quality issues, threshold adjustments made for this company)

    Example (post-intelligence-layer):
      title: "2 stalled deals — $340,000 at risk"
      detail: "Apex Corp ($220k, Sarah Chen) has been in Negotiation for 34 days
               — 1.7x your median deal cycle. Beacon Industries ($120k, Tom Park)
               has been in Proposal for 28 days with 40% probability."
      severity: HIGH
      recommended_action: "Schedule 30-min deal reviews: Apex Corp this week
               (exec sponsor call recommended — deal size warrants escalation);
               Beacon Industries — re-qualify or move to closed lost."
      confidence: "high"
      specific_entities: [
          {"type": "opportunity", "name": "Apex Corp", "id": "opp-123",
           "owner": "Sarah Chen", "amount": 220000, "days_stalled": 34},
          {"type": "opportunity", "name": "Beacon Industries", "id": "opp-456",
           "owner": "Tom Park", "amount": 120000, "days_stalled": 28},
      ]
    """
    title: str
    detail: str
    severity: Severity
    data: dict[str, Any] = field(default_factory=dict)
    recommended_action: str = ""
    # ── Schema Intelligence Layer fields (added Sprint N+1) ────────────────
    confidence: str = "high"                          # "high" | "medium" | "low" | "uncertain"
    specific_entities: list[dict[str, Any]] = field(default_factory=list)
    context_note: str = ""                            # caveat about thresholds or data quality


@dataclass
class WorkerResult:
    """
    The full output of one Worker's analysis.

    Contains:
      - worker_name: which worker produced this (for attribution)
      - tenant_id: which tenant was analysed
      - findings: the list of observations, sorted by severity
      - summary_stats: key metrics for the executive summary
      - error: if the worker failed, the error message (findings will be empty)
    """
    worker_name: str
    tenant_id: str
    findings: list[Finding] = field(default_factory=list)
    summary_stats: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON and for passing to Claude."""
        return {
            "worker": self.worker_name,
            "tenant_id": self.tenant_id,
            "summary_stats": self.summary_stats,
            "findings": [
                {
                    "title": f.title,
                    "detail": f.detail,
                    "severity": f.severity.value,
                    "data": f.data,
                    "recommended_action": f.recommended_action,
                    "confidence": f.confidence,
                    "specific_entities": f.specific_entities,
                    "context_note": f.context_note,
                }
                for f in self.findings
            ],
            "error": self.error,
        }


class WorkerBase(ABC):
    """
    Abstract base class for all Intelligence Workers.

    Subclasses must implement run() and return a WorkerResult.
    They receive a Neo4j driver at construction time — all data access
    goes through that driver. No HTTP calls, no file I/O.
    """

    WORKER_NAME: str = NotImplemented  # e.g. "WorkforceWorker"

    def __init__(self, driver) -> None:
        self.driver = driver

    @abstractmethod
    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        """
        Analyse the digital twin for this tenant and return findings.

        Args:
            tenant_id: The tenant to analyse.
            context:   Optional WorkerContext from the Schema Intelligence Layer.
                       When provided, workers use calibrated thresholds and
                       company-specific stage mappings instead of hardcoded defaults.
                       When None, workers fall back to pre-intelligence behavior.

        Must be safe to call multiple times (idempotent reads).
        Must not modify the graph.
        Must handle exceptions internally — return WorkerResult(error=...)
        rather than raising, so one failed worker doesn't stop the others.
        """
        ...
