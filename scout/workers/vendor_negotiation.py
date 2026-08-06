"""
scout/workers/vendor_negotiation.py — Vendor Negotiation Worker

Goes beyond the VendorWorker's renewal timing to produce actionable
negotiation intelligence: what to ask for, what leverage you have,
and how much you can realistically save.

The VendorWorker flags that a contract is renewing in 60 days.
The VendorNegotiationWorker answers: how should you negotiate it?

PE firms consistently extract 15-25% savings on SaaS and services
renewals through structured negotiation. The typical mid-market
company leaves $200k-$500k/year on the table by auto-renewing.

What this worker produces:
  1. Tiered negotiation brief for each upcoming renewal — leverage,
     benchmark, recommended ask, escalation path
  2. Multi-year lock-in risk — vendors who have auto-renewed into
     unfavorable long-term commitments
  3. Vendor concentration leverage — you're spending a lot with one
     vendor; that's actually negotiating power if used correctly
  4. Payment term arbitrage — vendors with upfront billing where
     Net 30 or Net 60 would improve working capital

This feeds the Renewal Workflow Worker Agent (Sprint 9), which will
take the brief produced here and draft the actual negotiation emails.
"""

import logging
from datetime import date, datetime

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)


class VendorNegotiationWorker(WorkerBase):
    """
    Produces negotiation intelligence for upcoming vendor renewals.
    """

    WORKER_NAME = "VendorNegotiationWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            all_vendors = self._get_all_vendors(tenant_id)
            upcoming = self._get_upcoming_renewals(tenant_id, cfg.get("negotiation_window_days"))
            critical = self._get_upcoming_renewals(tenant_id, cfg.get("critical_window_days"))

            total_annual_spend = sum(v.get("annual_spend") or 0 for v in all_vendors)
            upcoming_renewal_value = sum(v.get("annual_spend") or 0 for v in upcoming)
            estimated_savings = upcoming_renewal_value * cfg.get("typical_savings_pct")

            result.summary_stats = {
                "total_vendor_count": len(all_vendors),
                "total_annual_spend": round(total_annual_spend),
                "renewals_in_90_days": len(upcoming),
                "renewals_in_30_days": len(critical),
                "upcoming_renewal_value": round(upcoming_renewal_value),
                "estimated_negotiation_savings": round(estimated_savings),
            }

            if not all_vendors:
                result.findings.append(Finding(
                    title="No vendor data found — run an ERP scan first",
                    detail="VendorNegotiationWorker requires vendor data from NetSuite or another ERP connector.",
                    severity=Severity.INFO,
                    data={},
                ))
                return result

            # ── Finding 1: Critical window — time pressure ───────────────
            if critical:
                crit_spend = sum(v.get("annual_spend") or 0 for v in critical)
                crit_names = [v.get("vendor") for v in critical[:3]]
                result.findings.append(Finding(
                    title=f"{len(critical)} renewal{'s' if len(critical) > 1 else ''} in <30 days — ${crit_spend:,.0f} at risk of auto-renewal",
                    detail=(
                        f"{', '.join(crit_names)}{'...' if len(critical) > 3 else ''} "
                        f"renew within 30 days. At this point you have limited leverage — "
                        f"the vendor knows you cannot switch in time. "
                        f"Act immediately to avoid auto-renewing at current rates."
                    ),
                    severity=Severity.CRITICAL,
                    data={
                        "critical_count": len(critical),
                        "critical_spend": round(crit_spend),
                        "vendors": [{"name": v.get("vendor"), "renewal_date": v.get("renewal_date"), "spend": v.get("annual_spend")} for v in critical],
                    },
                    recommended_action=(
                        "Contact each vendor today. Even in the critical window, "
                        "you can negotiate: threaten to reduce seats, request a 1-year instead "
                        "of multi-year term, or ask for a 'loyalty discount' to renew quickly. "
                        "Worst case: negotiate a 30-day extension to do this properly."
                    ),
                ))

            # ── Finding 2: Full negotiation window (30-90 days) ──────────
            negotiation_window = [v for v in upcoming if v not in critical]
            if negotiation_window:
                for vendor in negotiation_window[:4]:
                    spend = vendor.get("annual_spend") or 0
                    savings_est = spend * cfg.get("typical_savings_pct")
                    days = vendor.get("days_until_renewal") or 0
                    leverage_note = self._leverage_note(vendor, all_vendors, total_annual_spend, cfg)
                    severity = Severity.HIGH if spend >= cfg.get("high_leverage_spend") else Severity.MEDIUM

                    result.findings.append(Finding(
                        title=f"{vendor.get('vendor')} renews in {days} days — ${spend:,.0f}/yr, est. ${savings_est:,.0f} savings available",
                        detail=(
                            f"${spend:,.0f}/year contract renews {vendor.get('renewal_date')}. "
                            f"{leverage_note} "
                            f"Target: {cfg.get('typical_savings_pct')*100:.0f}% savings = ${savings_est:,.0f}/yr."
                        ),
                        severity=severity,
                        data={
                            "vendor": vendor.get("vendor"),
                            "annual_spend": spend,
                            "renewal_date": vendor.get("renewal_date"),
                            "days_until_renewal": days,
                            "category": vendor.get("category"),
                            "payment_terms": vendor.get("payment_terms"),
                            "estimated_savings": round(savings_est),
                        },
                        recommended_action=(
                            f"Initiate negotiation this week. "
                            f"Lead with: seat reduction (right-size to actual utilization), "
                            f"multi-year pricing if rate is locked, and payment terms (Net 30 vs upfront)."
                        ),
                        confidence="medium",
                        specific_entities=[vendor.get("vendor")],
                    ))

            # ── Finding 3: Vendor concentration leverage ─────────────────
            if total_annual_spend > 0:
                for vendor in all_vendors:
                    spend = vendor.get("annual_spend") or 0
                    pct = (spend / total_annual_spend) * 100
                    if pct >= cfg.get("concentration_pct") and spend >= cfg.get("high_leverage_spend"):
                        result.findings.append(Finding(
                            title=f"{vendor.get('name')} is {pct:.0f}% of total vendor spend — high negotiating leverage",
                            detail=(
                                f"${spend:,.0f}/year ({pct:.0f}% of total spend) with "
                                f"{vendor.get('name')}. This concentration gives you significant "
                                f"negotiating power — they need you as much as you need them. "
                                f"Request executive-level QBR and use it to negotiate pricing."
                            ),
                            severity=Severity.INFO,
                            data={
                                "vendor": vendor.get("name"),
                                "spend": spend,
                                "pct_of_total": round(pct, 1),
                                "total_spend": round(total_annual_spend),
                            },
                            recommended_action=(
                                "Schedule a strategic review with your vendor rep's manager. "
                                "Position as a potential multi-year expansion in exchange for "
                                "a meaningful pricing concession (target 15-20%)."
                            ),
                        ))
                        break  # flag only the top one

            # ── Finding 4: Upfront billing candidates (working capital) ──
            upfront_vendors = [
                v for v in all_vendors
                if v.get("payment_terms") in ("Annual", "Upfront", "Annual Prepaid")
                and (v.get("annual_spend") or 0) > 50_000
            ]
            if upfront_vendors:
                upfront_spend = sum(v.get("annual_spend") or 0 for v in upfront_vendors)
                result.findings.append(Finding(
                    title=f"{len(upfront_vendors)} high-spend vendor{'s' if len(upfront_vendors) > 1 else ''} billing upfront — ${upfront_spend:,.0f} tied up annually",
                    detail=(
                        f"{len(upfront_vendors)} vendor(s) totaling ${upfront_spend:,.0f}/year "
                        f"are billed annually upfront. Converting even half to monthly or "
                        f"Net 30 improves free cash flow by ${upfront_spend/2:,.0f}."
                    ),
                    severity=Severity.LOW,
                    data={
                        "upfront_vendor_count": len(upfront_vendors),
                        "total_upfront_spend": round(upfront_spend),
                        "vendors": [{"name": v.get("name"), "spend": v.get("annual_spend")} for v in upfront_vendors[:5]],
                    },
                    recommended_action=(
                        "At next renewal for each, negotiate monthly billing or Net 30 quarterly. "
                        "Most SaaS vendors will agree to monthly at a small premium — "
                        "calculate whether the cash flow benefit outweighs the cost."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"VendorNegotiationWorker failed: {exc}")
            result.error = str(exc)

        return result

    def _leverage_note(self, vendor: dict, all_vendors: list[dict], total_spend: float, cfg) -> str:
        """Generate a short leverage note for the negotiation brief."""
        spend = vendor.get("annual_spend") or 0
        notes = []
        if spend >= cfg.get("high_leverage_spend"):
            notes.append("High-value contract gives you strong negotiating position.")
        cat = vendor.get("category")
        if cat:
            same_cat = [v for v in all_vendors if v.get("category") == cat and v.get("name") != vendor.get("vendor")]
            if same_cat:
                notes.append(f"You have {len(same_cat)} other {cat} vendor(s) — credible switch threat.")
        return " ".join(notes) or "Cite market alternatives and utilization data."

    def _get_all_vendors(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id, is_active: true})
        RETURN v.name AS name, v.category AS category,
               v.annual_spend AS annual_spend, v.payment_terms AS payment_terms,
               v.contract_renewal AS contract_renewal
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_upcoming_renewals(self, tenant_id: str, within_days: int) -> list[dict]:
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id, is_active: true})
        WHERE v.contract_renewal IS NOT NULL
          AND date(v.contract_renewal) >= date()
          AND date(v.contract_renewal) <= date() + duration({days: $days})
        RETURN
            v.name AS vendor,
            v.category AS category,
            v.annual_spend AS annual_spend,
            v.payment_terms AS payment_terms,
            v.contract_renewal AS renewal_date,
            duration.between(date(), date(v.contract_renewal)).days AS days_until_renewal
        ORDER BY days_until_renewal ASC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id, days=within_days)]
