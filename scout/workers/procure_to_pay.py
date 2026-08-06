"""
scout/workers/procure_to_pay.py — Procure-to-Pay Process Mining Worker

Mines the Procure-to-Pay (P2P) process using vendor data stored in the
digital twin. AP cycle efficiency is one of the highest-leverage working
capital levers available to mid-market companies — and one of the most
consistently under-managed.

The logic is simple: every day you delay paying a supplier is a day you
keep cash on your balance sheet earning a return. Every day a supplier
forces you to pay early is a day you've handed them an interest-free loan.
PE operating teams routinely extract 30–60 days of additional payment terms
during the first 12 months post-acquisition, freeing $500k–$2M of working
capital in a $30M ARR company.

What this worker analyses:
  1. Unfavorable payment terms — vendors on Due-on-Receipt or Net-15 are
     draining working capital. These are the highest-priority renegotiation
     targets.
  2. Favorable terms already in place — vendors on Net-60 or Net-90 are
     wins to protect and extend. They should not be renegotiated backward.
  3. AP concentration risk — if three vendors represent more than half of
     total spend, the business has a vendor dependency that creates leverage
     risk at renewal time.
  4. Unmanaged high-spend vendors — significant spend with no documented
     payment terms is invisible AP risk. These vendors could be on any terms
     and the company wouldn't know.
  5. Working capital improvement estimate — a concrete dollar figure showing
     what AP terms renegotiation is worth in free cash flow terms.

Roadmap:
  Sprint 12 will add an ERP connector (NetSuite or QuickBooks) for invoice-
  level P2P mining. At that point this worker will report true days payable
  outstanding (DPO), early payment discount capture rate, and invoice-to-
  approval cycle time — the full P2P process KPI suite.

Data source: Vendor nodes in Neo4j. No live ERP calls are made here —
all analysis runs against the digital twin.
"""

import logging
from collections import Counter

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
NET_30_TERMS        = {"Net 30", "Net30", "net30", "net 30"}
FAVORABLE_TERMS     = {"Net 60", "Net 90", "Net60", "Net90", "net60", "net90",
                       "net 60", "net 90"}
UNFAVORABLE_TERMS   = {"Due on Receipt", "Net 15", "Net15", "net15", "COD",
                       "Due On Receipt", "due on receipt"}

# Working capital improvement estimate basis:
# Moving from Net-15 to Net-30 frees (spend × 15 / 365) of cash
UNFAVORABLE_TO_NET30_DAYS = 15   # days of additional float gained per vendor renegotiated


class ProcureToPayWorker(WorkerBase):
    """
    Surfaces payment terms risk, AP concentration, unmanaged spend, and
    working capital improvement opportunities from Vendor nodes in the
    digital twin.

    AP optimisation is typically the fastest path to free cash flow improvement
    in a PE-backed company — most savings require zero headcount and zero capex.
    """

    WORKER_NAME = "ProcureToPayWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            vendors = self._get_vendors(tenant_id)

            if not vendors:
                result.findings.append(Finding(
                    title="No vendor data found — run an ERP or CRM scan first",
                    detail=(
                        "ProcureToPayWorker requires Vendor nodes in the graph. "
                        "Connect a NetSuite, QuickBooks, or CRM connector with vendor "
                        "data and run a scan."
                    ),
                    severity=Severity.INFO,
                    data={},
                    recommended_action=(
                        "Enable an ERP connector (NetSuite or QuickBooks) and trigger a scan. "
                        "Alternatively, upload a vendor export CSV via the manual ingestion endpoint."
                    ),
                ))
                result.summary_stats = {
                    "total_vendors": 0,
                    "total_annual_spend": 0,
                    "vendors_with_terms": 0,
                    "unmanaged_vendors": 0,
                    "favorable_terms_pct": 0.0,
                    "unfavorable_terms_pct": 0.0,
                    "potential_wc_improvement": 0,
                }
                return result

            # ── Partition vendors ──────────────────────────────────────────
            total_annual_spend = sum(v.get("annual_spend") or 0 for v in vendors)

            vendors_with_terms = [
                v for v in vendors if v.get("payment_terms")
            ]
            unmanaged_vendors = [
                v for v in vendors
                if not v.get("payment_terms")
                and (v.get("annual_spend") or 0) >= cfg.get("unmanaged_threshold")
            ]

            unfavorable = [
                v for v in vendors
                if v.get("payment_terms") in UNFAVORABLE_TERMS
            ]
            favorable = [
                v for v in vendors
                if v.get("payment_terms") in FAVORABLE_TERMS
            ]

            unfavorable_spend = sum(v.get("annual_spend") or 0 for v in unfavorable)
            favorable_spend   = sum(v.get("annual_spend") or 0 for v in favorable)

            favorable_terms_pct = (
                round(len(favorable) / len(vendors_with_terms) * 100, 1)
                if vendors_with_terms else 0.0
            )
            unfavorable_terms_pct = (
                round(len(unfavorable) / len(vendors_with_terms) * 100, 1)
                if vendors_with_terms else 0.0
            )

            # WC improvement estimate: moving unfavorable to Net-30 frees cash
            potential_wc_improvement = round(
                unfavorable_spend * UNFAVORABLE_TO_NET30_DAYS / 365
            )

            result.summary_stats = {
                "total_vendors": len(vendors),
                "total_annual_spend": round(total_annual_spend),
                "vendors_with_terms": len(vendors_with_terms),
                "unmanaged_vendors": len(unmanaged_vendors),
                "favorable_terms_pct": favorable_terms_pct,
                "unfavorable_terms_pct": unfavorable_terms_pct,
                "potential_wc_improvement": potential_wc_improvement,
            }

            # ── Finding 1: Unfavorable payment terms ──────────────────────
            high_spend_unfavorable = [
                v for v in unfavorable
                if (v.get("annual_spend") or 0) >= cfg.get("high_spend_threshold")
            ]
            if unfavorable:
                # Show high-spend ones first; include all in data
                display_vendors = high_spend_unfavorable if high_spend_unfavorable else unfavorable
                top_names = ", ".join(
                    f"{v.get('name')} ({v.get('payment_terms')}, ${v.get('annual_spend') or 0:,.0f}/yr)"
                    for v in sorted(display_vendors, key=lambda v: -(v.get("annual_spend") or 0))[:3]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(unfavorable)} vendor{'s' if len(unfavorable) != 1 else ''} on "
                        f"unfavorable payment terms — ${unfavorable_spend:,.0f}/yr at risk"
                    ),
                    detail=(
                        f"{len(unfavorable)} vendor{'s are' if len(unfavorable) != 1 else ' is'} "
                        f"on Due-on-Receipt, Net-15, or COD terms — each a working capital drain. "
                        f"These vendors are effectively receiving an interest-free short-term loan "
                        f"from you every billing cycle. "
                        f"Top examples: {top_names}. "
                        f"Renegotiating these to Net-30 would free approximately "
                        f"${potential_wc_improvement:,.0f} of working capital annually "
                        f"({UNFAVORABLE_TO_NET30_DAYS} days × annual spend / 365)."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "unfavorable_vendor_count": len(unfavorable),
                        "unfavorable_spend": round(unfavorable_spend),
                        "high_spend_unfavorable_count": len(high_spend_unfavorable),
                        "unfavorable_to_net30_days": UNFAVORABLE_TO_NET30_DAYS,
                        "estimated_wc_gain": potential_wc_improvement,
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "payment_terms": v.get("payment_terms"),
                                "annual_spend": v.get("annual_spend"),
                                "category": v.get("category"),
                            }
                            for v in sorted(unfavorable, key=lambda v: -(v.get("annual_spend") or 0))
                        ],
                    },
                    recommended_action=(
                        "Schedule renegotiation calls with the top unfavorable-terms vendors "
                        "ranked by spend. Frame as a 'preferred vendor programme' extension "
                        "in exchange for Net-30 terms. Start with the highest-spend vendor — "
                        "one negotiation can often free >$50k of working capital."
                    ),
                ))

            # ── Finding 2: Favorable terms wins ───────────────────────────
            if favorable:
                top_favorable = sorted(
                    favorable, key=lambda v: -(v.get("annual_spend") or 0)
                )[:5]
                names = ", ".join(
                    f"{v.get('name')} ({v.get('payment_terms')})"
                    for v in top_favorable
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(favorable)} vendor{'s' if len(favorable) != 1 else ''} already on "
                        f"favorable Net-60/90 terms — ${favorable_spend:,.0f}/yr protected"
                    ),
                    detail=(
                        f"{len(favorable)} vendor{'s have' if len(favorable) != 1 else ' has'} "
                        f"Net-60 or Net-90 payment terms, representing ${favorable_spend:,.0f}/yr "
                        f"of spend with built-in working capital benefit. "
                        f"These terms must be preserved at every renewal — do not allow "
                        f"vendors to roll them back to Net-30 without a concession in return. "
                        f"Examples: {names}."
                    ),
                    severity=Severity.INFO,
                    data={
                        "favorable_vendor_count": len(favorable),
                        "favorable_spend": round(favorable_spend),
                        "favorable_terms_pct": favorable_terms_pct,
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "payment_terms": v.get("payment_terms"),
                                "annual_spend": v.get("annual_spend"),
                            }
                            for v in top_favorable
                        ],
                    },
                    recommended_action=(
                        "Flag all Net-60/90 vendors in the contract management system "
                        "as 'Protect at Renewal'. Brief the procurement manager: "
                        "any attempt by a vendor to tighten terms must be escalated before signing."
                    ),
                ))

            # ── Finding 3: AP concentration risk ──────────────────────────
            if total_annual_spend > 0 and len(vendors) >= 3:
                sorted_by_spend = sorted(
                    vendors, key=lambda v: -(v.get("annual_spend") or 0)
                )
                top3_spend = sum(
                    v.get("annual_spend") or 0 for v in sorted_by_spend[:3]
                )
                top3_pct = (top3_spend / total_annual_spend) * 100

                if top3_pct > cfg.get("concentration_pct"):
                    top3_names = ", ".join(
                        f"{v.get('name')} (${v.get('annual_spend') or 0:,.0f})"
                        for v in sorted_by_spend[:3]
                    )
                    result.findings.append(Finding(
                        title=(
                            f"AP concentration risk: top 3 vendors are "
                            f"{top3_pct:.0f}% of total spend (${top3_spend:,.0f})"
                        ),
                        detail=(
                            f"Top 3 vendors — {top3_names} — account for "
                            f"{top3_pct:.0f}% of total annual vendor spend (${total_annual_spend:,.0f}). "
                            f"This concentration means a single vendor dispute, service disruption, "
                            f"or pricing increase has an outsized impact on the P&L. "
                            f"It also limits negotiating leverage at renewal — you cannot credibly "
                            f"threaten to switch a vendor that holds 20%+ of your spend."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "top3_spend": round(top3_spend),
                            "top3_pct_of_total": round(top3_pct, 1),
                            "total_annual_spend": round(total_annual_spend),
                            "concentration_threshold_pct": cfg.get("concentration_pct"),
                            "top3_vendors": [
                                {
                                    "name": v.get("name"),
                                    "annual_spend": v.get("annual_spend"),
                                    "category": v.get("category"),
                                    "pct_of_total": round(
                                        ((v.get("annual_spend") or 0) / total_annual_spend) * 100, 1
                                    ),
                                }
                                for v in sorted_by_spend[:3]
                            ],
                        },
                        recommended_action=(
                            "Develop a dual-source strategy for any category where a single "
                            "vendor is >20% of total spend. Pilot a secondary vendor for at "
                            "least 10% of volume — this restores credible switch threat and "
                            "typically unlocks 10-15% pricing improvement at the next renewal."
                        ),
                    ))

            # ── Finding 4: Unmanaged high-spend vendors ────────────────────
            if unmanaged_vendors:
                unmanaged_spend = sum(
                    v.get("annual_spend") or 0 for v in unmanaged_vendors
                )
                top_unmanaged = sorted(
                    unmanaged_vendors, key=lambda v: -(v.get("annual_spend") or 0)
                )[:5]
                names = ", ".join(
                    f"{v.get('name')} (${v.get('annual_spend') or 0:,.0f}/yr)"
                    for v in top_unmanaged
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(unmanaged_vendors)} high-spend vendor"
                        f"{'s' if len(unmanaged_vendors) != 1 else ''} with no payment terms "
                        f"documented — ${unmanaged_spend:,.0f}/yr unmanaged"
                    ),
                    detail=(
                        f"{len(unmanaged_vendors)} vendor{'s' if len(unmanaged_vendors) != 1 else ''} "
                        f"with spend above ${cfg.get('unmanaged_threshold'):,.0f}/yr have no payment terms "
                        f"recorded in the system. This is invisible AP risk — the company may be "
                        f"paying these vendors on whatever terms the vendor prefers. "
                        f"Examples: {names}. "
                        f"Unmanaged spend is also a data quality risk: without documented terms, "
                        f"AP teams cannot enforce agreed payment windows."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "unmanaged_vendor_count": len(unmanaged_vendors),
                        "unmanaged_spend": round(unmanaged_spend),
                        "unmanaged_threshold": cfg.get("unmanaged_threshold"),
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "annual_spend": v.get("annual_spend"),
                                "category": v.get("category"),
                                "contract_end_date": v.get("contract_end_date"),
                            }
                            for v in top_unmanaged
                        ],
                    },
                    recommended_action=(
                        "Pull the invoices for each unmanaged vendor and confirm the actual "
                        "payment terms in effect. Update the vendor record in the ERP or "
                        "CRM immediately. For vendors above $50k/yr, negotiate formal "
                        "written payment terms as part of the next order cycle."
                    ),
                ))

            # ── Finding 5: Working capital improvement estimate ────────────
            if potential_wc_improvement > 0:
                result.findings.append(Finding(
                    title=(
                        f"Working capital opportunity: ~${potential_wc_improvement:,.0f} "
                        f"recoverable by renegotiating unfavorable payment terms to Net-30"
                    ),
                    detail=(
                        f"If all {len(unfavorable)} vendor{'s' if len(unfavorable) != 1 else ''} "
                        f"currently on unfavorable terms (${unfavorable_spend:,.0f}/yr) were "
                        f"renegotiated to Net-30, the estimated working capital improvement is "
                        f"${potential_wc_improvement:,.0f} "
                        f"(= ${unfavorable_spend:,.0f} × {UNFAVORABLE_TO_NET30_DAYS} days / 365). "
                        f"This cash stays on the balance sheet rather than in the vendor's account. "
                        f"At a 5% cost of capital, this improvement has an annual economic value "
                        f"of ~${round(potential_wc_improvement * 0.05):,.0f}."
                    ),
                    severity=Severity.INFO,
                    data={
                        "unfavorable_vendor_count": len(unfavorable),
                        "unfavorable_spend": round(unfavorable_spend),
                        "days_improvement": UNFAVORABLE_TO_NET30_DAYS,
                        "estimated_wc_improvement": potential_wc_improvement,
                        "annual_economic_value_at_5pct_coc": round(
                            potential_wc_improvement * 0.05
                        ),
                    },
                    recommended_action=(
                        "Present this WC improvement estimate to the CFO as the business case "
                        "for a focused AP terms renegotiation programme."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"ProcureToPayWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Helper methods ──────────────────────────────────────────────────────

    def _get_vendors(self, tenant_id: str) -> list[dict]:
        """
        Fetch all Vendor nodes for the tenant with spend and terms data.

        Returns vendors ordered by annual_spend descending so concentration
        analysis and top-N slicing is efficient without additional sorting.
        """
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id})
        RETURN
            v.canonical_id      AS canonical_id,
            v.name              AS name,
            v.category          AS category,
            v.annual_spend      AS annual_spend,
            v.payment_terms     AS payment_terms,
            v.contract_end_date AS contract_end_date
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
