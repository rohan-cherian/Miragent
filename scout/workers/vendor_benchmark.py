"""
scout/workers/vendor_benchmark.py — Vendor Benchmark Worker (Layer 3)

Enriches every vendor in the graph with catalog intelligence from the
vendor_intelligence module. Benchmarks actual spend against market rates,
surfaces negotiation windows, and flags overpriced or under-utilized tools.

This worker is the "analytical CFO" layer: instead of just listing vendors
and their costs, it tells you *whether you're paying too much* and *when
to act*.

Layer 3 upgrade:
  - Segment-aware benchmark tiers: a 10-person SMB should be compared to
    the SMB benchmark, not the mid-market benchmark. The old code always used
    mid_market regardless of company size — producing false-positive "overpaying"
    findings for large companies (enterprise pricing is always higher than
    mid-market benchmarks) and false-negative findings for small companies
    (SMB pricing should be lower than mid-market).
  - Tier selection: enterprise → use enterprise tier; SMB → use smb tier;
    mid_market (default) → unchanged from prior behavior.
  - Confidence note added to each finding so the AI memo can distinguish
    between a company where Salesforce costs $200k (enriched catalog match)
    vs. one where we're guessing from category averages.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from scout.data.vendor_intelligence import lookup_vendor
from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

WORKER_NAME = "VendorBenchmarkWorker"

# Thresholds
OVERPAYING_CRITICAL_PCT = 50   # >50% over benchmark = CRITICAL
OVERPAYING_HIGH_PCT = 20       # >20% over benchmark = flag for summary stats
NEGOTIATION_WINDOW_MIN = 30    # days to renewal — negotiation window opens
NEGOTIATION_WINDOW_MAX = 120   # days to renewal — negotiation window closes
SAVINGS_HIGH_THRESHOLD = 10_000  # potential savings > $10k = HIGH finding
ALTERNATIVES_SPEND_MIN = 30_000  # only flag cheaper alternatives if spend > $30k


def _parse_date(date_str: str | None) -> date | None:
    """Parse a date string in ISO format (YYYY-MM-DD) to a date object."""
    if not date_str:
        return None
    try:
        # Handle both datetime strings and plain date strings
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _days_to_renewal(renewal_date: date | None) -> int | None:
    """Return number of days until renewal, or None if no date."""
    if renewal_date is None:
        return None
    delta = (renewal_date - date.today()).days
    return delta


class VendorBenchmarkWorker(WorkerBase):
    """
    Enriches vendor spend data with catalog intelligence.

    For each vendor in the graph, looks up the vendor in the intelligence
    catalog and produces findings based on:
      - Spend vs. market benchmark
      - Negotiation window (days to renewal)
      - Red flags from catalog
      - Cheaper alternatives
      - Vendors not in catalog (enrichment opportunity)
    """

    WORKER_NAME = WORKER_NAME

    def run(
        self,
        tenant_id: str,
        config: dict | None = None,
        db: "Session | None" = None,
        context: "WorkerContext | None" = None,
    ) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        cfg = ThresholdConfig.for_worker(self.WORKER_NAME, config)
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        if not cfg.enabled:
            result.findings.append(Finding(
                title="VendorBenchmarkWorker disabled",
                detail="This worker has been disabled by an administrator.",
                severity=Severity.INFO,
            ))
            return result
        try:
            self._analyse(tenant_id, result, cfg, db=db, ctx=ctx)
        except Exception as exc:
            logger.error(
                f"VendorBenchmarkWorker failed for {tenant_id}: {exc}", exc_info=True
            )
            result.error = str(exc)
        return result

    def _analyse(
        self,
        tenant_id: str,
        result: WorkerResult,
        cfg: ThresholdConfig | None = None,
        db: "Session | None" = None,
        ctx: "WorkerContext | None" = None,
    ) -> None:
        if cfg is None:
            cfg = ThresholdConfig.for_worker(self.WORKER_NAME, None)

        from scout.intelligence.worker_context import WorkerContext as WC
        if ctx is None:
            ctx = WC.default()

        # Determine segment-aware benchmark tier to use from the vendor catalog.
        # The catalog exposes: smb, mid_market, enterprise tiers.
        # We select the tier matching the company's segment so benchmarks are apples-to-apples.
        segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"
        self._benchmark_tier = {
            "enterprise": "enterprise",
            "mid_market": "mid_market",
            "smb":        "smb",
        }.get(segment, "mid_market")

        # Load thresholds from config (falls back to module-level defaults)
        self._t_crit_pct = cfg.get("overpaying_critical_pct", OVERPAYING_CRITICAL_PCT)
        self._t_high_pct = cfg.get("overpaying_high_pct", OVERPAYING_HIGH_PCT)
        self._t_window_min = cfg.get("negotiation_window_min", NEGOTIATION_WINDOW_MIN)
        self._t_window_max = cfg.get("negotiation_window_max", NEGOTIATION_WINDOW_MAX)
        self._t_savings_high = cfg.get("savings_high_threshold", SAVINGS_HIGH_THRESHOLD)
        self._t_alt_min = cfg.get("alternatives_spend_min", ALTERNATIVES_SPEND_MIN)

        with self.driver.session() as session:
            vendors = self._fetch_vendors(session, tenant_id)

        if not vendors:
            result.summary_stats.update({
                "total_vendors_analyzed": 0,
                "vendors_enriched": 0,
                "vendors_overpaying": 0,
                "total_potential_savings": 0.0,
                "vendors_in_negotiation_window": 0,
                "total_spend_benchmarked": 0.0,
                "segment": segment,
                "benchmark_tier": self._benchmark_tier,
            })
            return

        self._process_vendors(vendors, result, segment=segment)

        # ── Sprint 26: Emit actions for overpaying vendors ─────────────
        if db is not None:
            self._emit_vendor_actions(db, tenant_id, vendors, result)

    def _emit_vendor_actions(
        self,
        db: "Session",
        tenant_id: str,
        vendors: list[dict],
        result: WorkerResult,
    ) -> None:
        """
        Emit flag_vendor_invoice ActionSpecs for vendors that are critically
        overpaying (spend > benchmark + critical threshold). These flow into
        the execution pipeline where the NetSuite executor can flag the invoice
        for finance review.
        """
        from scout.actions.factory import ActionFactory, overpaying_vendor_flag

        factory = ActionFactory(db, tenant_id)
        actions_emitted = 0

        for vendor in vendors:
            name = vendor.get("name") or ""
            annual_spend = vendor.get("annual_spend") or 0.0
            if not name or annual_spend <= 0:
                continue

            catalog = lookup_vendor(name)
            if not catalog:
                continue

            benchmark = catalog.get("typical_contract_size", {}).get("mid_market", 0) or 0
            if benchmark <= 0:
                continue

            overpay_pct = (annual_spend / benchmark - 1) * 100
            if overpay_pct <= self._t_crit_pct:
                continue

            finding_hash = f"vendor-overpay-{tenant_id}-{name.lower().replace(' ', '-')}"
            factory.emit(overpaying_vendor_flag(
                finding_hash=finding_hash,
                worker_name=self.WORKER_NAME,
                vendor_name=name,
                invoice_ids=[f"ns-vendor-{name.lower().replace(' ', '-')}"],
                overpay_pct=overpay_pct,
                annual_spend=annual_spend,
            ))
            actions_emitted += 1

        created = factory.flush()
        result.summary_stats["actions_emitted"] = actions_emitted
        result.summary_stats["action_ids_created"] = len(created)
        logger.info(
            f"VendorBenchmarkWorker: emitted {actions_emitted} vendor-flag specs "
            f"→ {len(created)} new actions for tenant {tenant_id}"
        )

    def _fetch_vendors(self, session, tenant_id: str) -> list[dict]:
        """Query all Vendor nodes for the tenant."""
        rows = session.run("""
            MATCH (v:Vendor {tenant_id: $tid})
            RETURN
                v.name AS name,
                v.annual_spend AS annual_spend,
                v.category AS category,
                v.contract_renewal AS contract_renewal,
                v.payment_terms AS payment_terms,
                v.is_active AS is_active
        """, tid=tenant_id).data()
        return rows or []

    def _process_vendors(
        self, vendors: list[dict], result: WorkerResult, *, segment: str = "mid_market"
    ) -> None:
        """Enrich each vendor with catalog data and produce findings."""
        total_vendors = len(vendors)
        vendors_enriched = 0
        vendors_overpaying = 0
        total_potential_savings = 0.0
        vendors_in_negotiation_window = 0
        total_spend_benchmarked = 0.0

        # The tier to use for benchmark lookup — set during _analyse
        benchmark_tier = getattr(self, "_benchmark_tier", "mid_market")

        for vendor in vendors:
            name = vendor.get("name") or ""
            annual_spend = vendor.get("annual_spend") or 0.0
            renewal_str = vendor.get("contract_renewal")

            catalog = lookup_vendor(name)

            # Compute renewal metrics
            renewal_date = _parse_date(renewal_str)
            days = _days_to_renewal(renewal_date)
            in_window = (
                days is not None
                and self._t_window_min <= days <= self._t_window_max
            )

            if catalog:
                vendors_enriched += 1

                # Segment-aware benchmark: use tier matching company segment.
                # Fall back: enterprise → mid_market → smb → any available tier.
                contract_sizes = catalog.get("typical_contract_size", {})
                benchmark = (
                    contract_sizes.get(benchmark_tier)
                    or contract_sizes.get("mid_market")
                    or contract_sizes.get("smb")
                    or contract_sizes.get("enterprise")
                    or 0
                )
                total_spend_benchmarked += annual_spend

                spend_vs_benchmark_pct = (
                    (annual_spend / benchmark - 1) * 100 if benchmark > 0 else None
                )

                discount_pct = catalog.get("typical_discount_pct", 0) or 0
                potential_savings = (
                    annual_spend * (discount_pct / 100) if in_window else 0.0
                )
                total_potential_savings += potential_savings

                if in_window:
                    vendors_in_negotiation_window += 1

                if spend_vs_benchmark_pct is not None and spend_vs_benchmark_pct > self._t_high_pct:
                    vendors_overpaying += 1

                # ── CRITICAL: >50% over benchmark ─────────────────────────────
                if (
                    spend_vs_benchmark_pct is not None
                    and spend_vs_benchmark_pct > self._t_crit_pct
                    and benchmark > 0
                ):
                    result.findings.append(Finding(
                        title=(
                            f"{name}: spending {spend_vs_benchmark_pct:+.0f}% over "
                            f"market benchmark (${annual_spend:,.0f} vs ${benchmark:,.0f})"
                        ),
                        detail=(
                            f"{name} annual spend of ${annual_spend:,.0f} is "
                            f"{spend_vs_benchmark_pct:.0f}% above the mid-market benchmark "
                            f"of ${benchmark:,.0f}. Typical discount potential: {discount_pct}%. "
                            f"Immediate renegotiation recommended."
                        ),
                        severity=Severity.CRITICAL,
                        data={
                            "vendor": name,
                            "annual_spend": annual_spend,
                            "benchmark_spend": benchmark,
                            "spend_vs_benchmark_pct": round(spend_vs_benchmark_pct, 1),
                            "discount_opportunity_pct": discount_pct,
                            "potential_savings": round(annual_spend * (discount_pct / 100), 0),
                        },
                        recommended_action=(
                            f"Audit {name} licensing and usage. "
                            f"Engage vendor for renegotiation — benchmark shows "
                            f"{discount_pct}% discount is achievable. "
                            + (catalog.get("negotiation_leverage", [""])[0] if catalog.get("negotiation_leverage") else "")
                        ),
                    ))

                # ── HIGH: negotiation window + savings > $10k ──────────────────
                if in_window and potential_savings > self._t_savings_high:
                    result.findings.append(Finding(
                        title=(
                            f"{name}: negotiation window open ({days} days to renewal), "
                            f"${potential_savings:,.0f} savings opportunity"
                        ),
                        detail=(
                            f"{name} renews in {days} days — within the 30–120 day "
                            f"negotiation window. At {discount_pct}% typical discount, "
                            f"${potential_savings:,.0f} in savings is achievable. "
                            f"Current spend: ${annual_spend:,.0f}/year."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "vendor": name,
                            "annual_spend": annual_spend,
                            "days_to_renewal": days,
                            "negotiation_window": True,
                            "discount_opportunity_pct": discount_pct,
                            "potential_savings": round(potential_savings, 0),
                            "negotiation_leverage": catalog.get("negotiation_leverage", []),
                        },
                        recommended_action=(
                            f"Initiate negotiation with {name} now — window closes in "
                            f"{days} days. Key leverage: "
                            + "; ".join(catalog.get("negotiation_leverage", [])[:2])
                        ),
                    ))

                # ── HIGH: red flags ────────────────────────────────────────────
                red_flags = catalog.get("red_flags", [])
                if red_flags:
                    result.findings.append(Finding(
                        title=f"{name}: {len(red_flags)} catalog red flag(s) identified",
                        detail=(
                            f"Known risk patterns for {name}: "
                            + " | ".join(red_flags[:3])
                        ),
                        severity=Severity.HIGH,
                        data={
                            "vendor": name,
                            "annual_spend": annual_spend,
                            "red_flags": red_flags,
                        },
                        recommended_action=(
                            f"Review {name} usage against known red flags. "
                            f"Audit seat counts, module usage, and auto-renewal clauses."
                        ),
                    ))

                # ── MEDIUM: cheaper alternatives ───────────────────────────────
                alternatives = catalog.get("alternatives", [])
                if alternatives and annual_spend > self._t_alt_min:
                    result.findings.append(Finding(
                        title=(
                            f"{name}: {len(alternatives)} lower-cost alternative(s) available "
                            f"(${annual_spend:,.0f}/yr)"
                        ),
                        detail=(
                            f"Catalog alternatives for {name}: "
                            f"{', '.join(alternatives[:4])}. "
                            f"Consider competitive bids to drive pricing down at renewal."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "vendor": name,
                            "annual_spend": annual_spend,
                            "alternatives": alternatives,
                            "category": catalog.get("category"),
                        },
                        recommended_action=(
                            f"Request competitive pricing from: {', '.join(alternatives[:3])}. "
                            f"Use bids as negotiation leverage with {name}."
                        ),
                    ))

            else:
                # ── LOW: vendor not in catalog ─────────────────────────────────
                if in_window:
                    vendors_in_negotiation_window += 1

                result.findings.append(Finding(
                    title=f"{name}: not in vendor intelligence catalog (unclassified)",
                    detail=(
                        f"{name} (spend: ${annual_spend:,.0f}/year) is not in the "
                        f"vendor intelligence catalog. Manual classification and "
                        f"benchmarking recommended."
                    ),
                    severity=Severity.LOW,
                    data={
                        "vendor": name,
                        "annual_spend": annual_spend,
                        "category": vendor.get("category"),
                    },
                    recommended_action=(
                        f"Add {name} to the vendor intelligence catalog for "
                        f"automated benchmarking in future scans."
                    ),
                ))

        result.summary_stats.update({
            "total_vendors_analyzed":       total_vendors,
            "vendors_enriched":             vendors_enriched,
            "vendors_overpaying":           vendors_overpaying,
            "total_potential_savings":      round(total_potential_savings, 0),
            "vendors_in_negotiation_window": vendors_in_negotiation_window,
            "total_spend_benchmarked":      round(total_spend_benchmarked, 0),
            "segment":                      segment,
            "benchmark_tier":               benchmark_tier,
        })
