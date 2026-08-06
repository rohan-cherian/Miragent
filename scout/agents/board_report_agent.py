"""
BoardReportAgent — Sprint 70

Compiles a structured board package for the CEO/CFO before monthly or quarterly
board meetings. Instead of manually pulling data from Salesforce, Workday,
NetSuite, and spreadsheets, one button generates a full board report covering
ARR, pipeline, customer success, headcount, financials, DORA metrics, and
strategic risks.

Report sections (7 fixed):
  1. Revenue & ARR          (Salesforce / NetSuite mock)
  2. Sales Pipeline         (Salesforce mock)
  3. Customer Success       (churn, NPS, retention mock)
  4. Headcount & Org        (Workday mock)
  5. Financial Performance  (NetSuite mock — burn, runway, EBITDA)
  6. Product & Engineering  (DORA metrics mock)
  7. Strategic Risks        (synthesized from Scout findings)

All data is mocked for a representative ~$8M ARR SaaS company.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── Mock metrics ───────────────────────────────────────────────────────────────

BOARD_METRICS: dict = {
    "report_date": "2026-05-01",
    "period": "April 2026",
    "prior_period": "March 2026",

    "revenue": {
        "arr": 8_420_000,
        "arr_prior": 8_150_000,
        "mrr": 701_667,
        "mrr_prior": 679_167,
        "new_arr_mtd": 340_000,
        "churned_arr_mtd": 70_000,
        "expansion_arr_mtd": 45_000,
        "net_new_arr_mtd": 270_000,
        "logo_count": 127,
        "logo_count_prior": 124,
        "avg_contract_value": 66_300,
        "nrr": 0.107,        # net revenue retention as decimal (107%)
        "grr": 0.91,         # gross revenue retention (91%)
    },

    "pipeline": {
        "total_pipeline": 4_800_000,
        "total_pipeline_prior": 4_200_000,
        "weighted_pipeline": 2_160_000,
        "stage_1_2": 1_440_000,
        "stage_3_4": 2_100_000,
        "stage_5_plus": 1_260_000,
        "deals_above_100k": 8,
        "avg_deal_size": 72_000,
        "avg_cycle_days": 68,
        "avg_cycle_days_prior": 74,
        "win_rate": 0.28,
        "win_rate_prior": 0.25,
        "pipeline_coverage": 5.7,
    },

    "customer_success": {
        "nps_score": 42,
        "nps_prior": 38,
        "churn_rate_monthly": 0.009,
        "churn_rate_prior": 0.011,
        "at_risk_arr": 320_000,
        "at_risk_arr_prior": 410_000,
        "onboarded_mtd": 4,
        "support_tickets_open": 23,
        "support_tickets_prior": 31,
        "median_resolution_hrs": 8.4,
        "csat": 0.87,
    },

    "headcount": {
        "total": 48,
        "total_prior": 46,
        "engineering": 18,
        "sales": 10,
        "cs": 7,
        "marketing": 5,
        "finance_ops": 4,
        "hr_legal": 4,
        "hires_mtd": 3,
        "departures_mtd": 1,
        "open_reqs": 7,
        "contractor_count": 4,
        "arr_per_employee": 175_417,
    },

    "financials": {
        "revenue_recognized": 695_000,
        "cogs": 138_000,
        "gross_profit": 557_000,
        "gross_margin": 0.802,
        "opex": 890_000,
        "ebitda": -333_000,
        "ebitda_margin": -0.479,
        "cash_burn_monthly": 318_000,
        "cash_burn_prior": 342_000,
        "cash_on_hand": 6_840_000,
        "runway_months": 21.5,
        "payroll_pct_opex": 0.74,
        "rd_pct_revenue": 0.38,
        "sm_pct_revenue": 0.27,
        "ga_pct_revenue": 0.12,
    },

    "engineering": {
        "deployment_frequency_per_week": 8.2,
        "deployment_freq_prior": 7.1,
        "lead_time_hrs": 18.4,
        "lead_time_prior_hrs": 22.1,
        "change_failure_rate": 0.032,
        "mttr_hrs": 1.8,
        "sprint_velocity": 94,
        "sprint_velocity_prior": 88,
        "prs_merged_mtd": 142,
        "open_prs": 7,
        "test_coverage": 0.78,
        "incidents_mtd": 2,
        "p1_incidents": 0,
    },
}

STRATEGIC_RISKS: list[dict] = [
    {
        "risk": "Pipeline concentration",
        "detail": (
            "Top 3 deals represent 31% of weighted pipeline. "
            "Loss of any single deal would materially impact Q2 close."
        ),
        "severity": "HIGH",
    },
    {
        "risk": "Cash runway",
        "detail": (
            "At current burn rate, runway is 21.5 months. "
            "Series B target is 18 months out. "
            "Burn improvement or bridge required by Q4."
        ),
        "severity": "MEDIUM",
    },
    {
        "risk": "Engineering capacity",
        "detail": (
            "7 open engineering reqs with 18-week average time-to-fill. "
            "Feature velocity may compress in Q3 if not resolved."
        ),
        "severity": "MEDIUM",
    },
]


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class MetricItem:
    label: str
    value: str           # formatted string (e.g., "$8.42M", "48", "21.5 months")
    prior_value: str | None
    change_pct: float | None
    direction: str       # "up" | "down" | "flat"
    is_positive: bool    # True if "up" is good for this metric


@dataclass
class ReportSection:
    section_id: str
    title: str
    narrative: str
    metrics: list[MetricItem] = field(default_factory=list)


@dataclass
class BoardReport:
    report_id: str
    tenant_id: str
    period: str
    generated_at: str
    sections: list[ReportSection]
    strategic_risks: list[dict]
    executive_summary: str
    dora_tier: str


# ── Agent ──────────────────────────────────────────────────────────────────────


class BoardReportAgent:
    """
    Generates a structured board report from mock data sources.

    No LLM required — all metrics are deterministic. Narratives are generated
    from templates so output is stable and auditable across regenerations.
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_report(
        self,
        tenant_id: str,
        period: str | None,
        db,  # noqa: ANN001 — passed through from route, unused in mock mode
    ) -> BoardReport:
        """
        Generate a full board report for the given tenant and period.

        Uses BOARD_METRICS (mock data) to build all seven sections, compute
        DORA classification, generate narrative commentary, and compose an
        executive summary.
        """
        logger.info(
            "BoardReportAgent.generate_report tenant=%s period=%s",
            tenant_id,
            period or BOARD_METRICS["period"],
        )

        resolved_period = period or BOARD_METRICS["period"]
        dora_tier = self._classify_dora()

        sections = [
            self._build_revenue_section(),
            self._build_pipeline_section(),
            self._build_cs_section(),
            self._build_headcount_section(),
            self._build_financials_section(),
            self._build_engineering_section(),
        ]

        executive_summary = self._build_executive_summary(dora_tier)

        return BoardReport(
            report_id=str(uuid4()),
            tenant_id=tenant_id,
            period=resolved_period,
            generated_at=datetime.now(timezone.utc).isoformat(),
            sections=sections,
            strategic_risks=STRATEGIC_RISKS,
            executive_summary=executive_summary,
            dora_tier=dora_tier,
        )

    # ── Section builders ───────────────────────────────────────────────────────

    def _build_revenue_section(self) -> ReportSection:
        rv = BOARD_METRICS["revenue"]
        arr_chg = self._pct_change(rv["arr"], rv["arr_prior"])
        logo_chg = self._pct_change(rv["logo_count"], rv["logo_count_prior"])

        narrative = (
            f"ARR grew {arr_chg:+.1f}% MoM to {self._format_currency(rv['arr'])}, "
            f"driven by {self._format_currency(rv['new_arr_mtd'])} in new bookings and "
            f"{self._format_currency(rv['expansion_arr_mtd'])} in expansion against "
            f"{self._format_currency(rv['churned_arr_mtd'])} in churn. "
            f"Net revenue retention of {self._format_pct(rv['nrr'] + 1.0)} reflects strong "
            f"expansion motion with gross retention holding at {self._format_pct(rv['grr'])}. "
            f"Logo count reached {rv['logo_count']} (+{rv['logo_count'] - rv['logo_count_prior']} MoM), "
            f"up {logo_chg:+.1f}% versus prior period."
        )

        metrics = [
            MetricItem(
                label="ARR",
                value=self._format_currency(rv["arr"]),
                prior_value=self._format_currency(rv["arr_prior"]),
                change_pct=arr_chg,
                direction="up" if arr_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="MRR",
                value=self._format_currency(rv["mrr"]),
                prior_value=self._format_currency(rv["mrr_prior"]),
                change_pct=self._pct_change(rv["mrr"], rv["mrr_prior"]),
                direction="up",
                is_positive=True,
            ),
            MetricItem(
                label="Net New ARR (MTD)",
                value=self._format_currency(rv["net_new_arr_mtd"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Logo Count",
                value=str(rv["logo_count"]),
                prior_value=str(rv["logo_count_prior"]),
                change_pct=logo_chg,
                direction="up" if logo_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="Net Revenue Retention",
                value=self._format_pct(rv["nrr"] + 1.0),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Gross Revenue Retention",
                value=self._format_pct(rv["grr"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Avg Contract Value",
                value=self._format_currency(rv["avg_contract_value"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
        ]

        return ReportSection(
            section_id="revenue",
            title="Revenue & ARR",
            narrative=narrative,
            metrics=metrics,
        )

    def _build_pipeline_section(self) -> ReportSection:
        pl = BOARD_METRICS["pipeline"]
        pipe_chg = self._pct_change(pl["total_pipeline"], pl["total_pipeline_prior"])
        cycle_chg = self._pct_change(pl["avg_cycle_days"], pl["avg_cycle_days_prior"])
        wr_chg = self._pct_change(pl["win_rate"], pl["win_rate_prior"])

        narrative = (
            f"Total pipeline grew to {self._format_currency(pl['total_pipeline'])} "
            f"({pipe_chg:+.1f}% MoM), yielding a {pl['pipeline_coverage']}x coverage ratio "
            f"against current ARR — above the 3–4x benchmark for healthy SaaS pipelines. "
            f"Average deal cycle improved from {pl['avg_cycle_days_prior']} to {pl['avg_cycle_days']} days "
            f"({cycle_chg:+.1f}%), and win rate expanded to {self._format_pct(pl['win_rate'])} "
            f"from {self._format_pct(pl['win_rate_prior'])} in the prior period. "
            f"{pl['deals_above_100k']} deals above $100K represent meaningful upmarket traction."
        )

        metrics = [
            MetricItem(
                label="Total Pipeline",
                value=self._format_currency(pl["total_pipeline"]),
                prior_value=self._format_currency(pl["total_pipeline_prior"]),
                change_pct=pipe_chg,
                direction="up" if pipe_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="Weighted Pipeline",
                value=self._format_currency(pl["weighted_pipeline"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Pipeline Coverage",
                value=f"{pl['pipeline_coverage']}x",
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Win Rate",
                value=self._format_pct(pl["win_rate"]),
                prior_value=self._format_pct(pl["win_rate_prior"]),
                change_pct=wr_chg,
                direction="up" if wr_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="Avg Deal Size",
                value=self._format_currency(pl["avg_deal_size"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Avg Cycle Days",
                value=str(pl["avg_cycle_days"]),
                prior_value=str(pl["avg_cycle_days_prior"]),
                change_pct=cycle_chg,
                direction="down" if cycle_chg < 0 else "up",
                is_positive=False,  # fewer days is better, so "down" is positive
            ),
            MetricItem(
                label="Deals > $100K",
                value=str(pl["deals_above_100k"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
        ]

        return ReportSection(
            section_id="pipeline",
            title="Sales Pipeline",
            narrative=narrative,
            metrics=metrics,
        )

    def _build_cs_section(self) -> ReportSection:
        cs = BOARD_METRICS["customer_success"]
        nps_chg = self._pct_change(cs["nps_score"], cs["nps_prior"])
        churn_chg = self._pct_change(cs["churn_rate_monthly"], cs["churn_rate_prior"])
        risk_chg = self._pct_change(cs["at_risk_arr"], cs["at_risk_arr_prior"])

        narrative = (
            f"NPS improved to {cs['nps_score']} from {cs['nps_prior']} in the prior period, "
            f"reflecting stronger onboarding and support responsiveness. "
            f"Monthly churn rate declined to {self._format_pct(cs['churn_rate_monthly'])} "
            f"(from {self._format_pct(cs['churn_rate_prior'])}), the lowest rate in six months. "
            f"At-risk ARR contracted {abs(risk_chg):.1f}% MoM to {self._format_currency(cs['at_risk_arr'])}, "
            f"and open support tickets fell from {cs['support_tickets_prior']} to {cs['support_tickets_open']}."
        )

        metrics = [
            MetricItem(
                label="NPS Score",
                value=str(cs["nps_score"]),
                prior_value=str(cs["nps_prior"]),
                change_pct=nps_chg,
                direction="up" if nps_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="Monthly Churn Rate",
                value=self._format_pct(cs["churn_rate_monthly"]),
                prior_value=self._format_pct(cs["churn_rate_prior"]),
                change_pct=churn_chg,
                direction="down" if churn_chg < 0 else "up",
                is_positive=False,  # lower churn is better
            ),
            MetricItem(
                label="At-Risk ARR",
                value=self._format_currency(cs["at_risk_arr"]),
                prior_value=self._format_currency(cs["at_risk_arr_prior"]),
                change_pct=risk_chg,
                direction="down" if risk_chg < 0 else "up",
                is_positive=False,  # lower at-risk is better
            ),
            MetricItem(
                label="CSAT",
                value=self._format_pct(cs["csat"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Onboarded (MTD)",
                value=str(cs["onboarded_mtd"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Open Support Tickets",
                value=str(cs["support_tickets_open"]),
                prior_value=str(cs["support_tickets_prior"]),
                change_pct=self._pct_change(cs["support_tickets_open"], cs["support_tickets_prior"]),
                direction="down",
                is_positive=False,
            ),
            MetricItem(
                label="Median Resolution",
                value=f"{cs['median_resolution_hrs']}h",
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
        ]

        return ReportSection(
            section_id="customer_success",
            title="Customer Success",
            narrative=narrative,
            metrics=metrics,
        )

    def _build_headcount_section(self) -> ReportSection:
        hc = BOARD_METRICS["headcount"]
        hc_chg = self._pct_change(hc["total"], hc["total_prior"])
        ape_chg = self._pct_change(hc["arr_per_employee"], 8_150_000 / hc["total_prior"])

        narrative = (
            f"Headcount grew to {hc['total']} ({hc['hires_mtd']} hires, "
            f"{hc['departures_mtd']} departure MTD), up {hc_chg:+.1f}% MoM. "
            f"ARR per employee reached {self._format_currency(hc['arr_per_employee'])}, "
            f"improving {ape_chg:+.1f}% as revenue growth outpaced hiring pace. "
            f"Engineering remains the largest function at {hc['engineering']} headcount, "
            f"with {hc['open_reqs']} open requisitions across the org."
        )

        metrics = [
            MetricItem(
                label="Total Headcount",
                value=str(hc["total"]),
                prior_value=str(hc["total_prior"]),
                change_pct=hc_chg,
                direction="up" if hc_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="ARR per Employee",
                value=self._format_currency(hc["arr_per_employee"]),
                prior_value=None,
                change_pct=None,
                direction="up",
                is_positive=True,
            ),
            MetricItem(
                label="Hires MTD",
                value=str(hc["hires_mtd"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Open Requisitions",
                value=str(hc["open_reqs"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Engineering",
                value=str(hc["engineering"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Sales",
                value=str(hc["sales"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Contractors",
                value=str(hc["contractor_count"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
        ]

        return ReportSection(
            section_id="headcount",
            title="Headcount & Org",
            narrative=narrative,
            metrics=metrics,
        )

    def _build_financials_section(self) -> ReportSection:
        fin = BOARD_METRICS["financials"]
        burn_chg = self._pct_change(fin["cash_burn_monthly"], fin["cash_burn_prior"])

        narrative = (
            f"Monthly cash burn improved to {self._format_currency(fin['cash_burn_monthly'])} "
            f"from {self._format_currency(fin['cash_burn_prior'])} ({abs(burn_chg):.1f}% reduction), "
            f"extending runway to {fin['runway_months']} months against "
            f"{self._format_currency(fin['cash_on_hand'])} cash on hand. "
            f"Gross margin of {self._format_pct(fin['gross_margin'])} is above the 75% SaaS benchmark. "
            f"EBITDA margin of {self._format_pct(fin['ebitda_margin'])} reflects planned investment; "
            f"R&D and S&M represent {self._format_pct(fin['rd_pct_revenue'])} and "
            f"{self._format_pct(fin['sm_pct_revenue'])} of revenue respectively."
        )

        metrics = [
            MetricItem(
                label="Revenue Recognized",
                value=self._format_currency(fin["revenue_recognized"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Gross Margin",
                value=self._format_pct(fin["gross_margin"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="EBITDA",
                value=self._format_currency(fin["ebitda"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=False,
            ),
            MetricItem(
                label="Cash Burn (Monthly)",
                value=self._format_currency(fin["cash_burn_monthly"]),
                prior_value=self._format_currency(fin["cash_burn_prior"]),
                change_pct=burn_chg,
                direction="down" if burn_chg < 0 else "up",
                is_positive=False,  # lower burn is better
            ),
            MetricItem(
                label="Cash on Hand",
                value=self._format_currency(fin["cash_on_hand"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Runway",
                value=f"{fin['runway_months']} months",
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="Payroll % of OpEx",
                value=self._format_pct(fin["payroll_pct_opex"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
        ]

        return ReportSection(
            section_id="financials",
            title="Financial Performance",
            narrative=narrative,
            metrics=metrics,
        )

    def _build_engineering_section(self) -> ReportSection:
        eng = BOARD_METRICS["engineering"]
        dora_tier = self._classify_dora()
        dep_chg = self._pct_change(
            eng["deployment_frequency_per_week"],
            eng["deployment_freq_prior"],
        )
        vel_chg = self._pct_change(eng["sprint_velocity"], eng["sprint_velocity_prior"])

        narrative = (
            f"Engineering is classified as DORA '{dora_tier}' — deploying "
            f"{eng['deployment_frequency_per_week']} times per week "
            f"({dep_chg:+.1f}% vs prior), with {eng['lead_time_hrs']}h lead time "
            f"(improved from {eng['lead_time_prior_hrs']}h). "
            f"Change failure rate of {self._format_pct(eng['change_failure_rate'])} and "
            f"MTTR of {eng['mttr_hrs']}h are well within healthy ranges. "
            f"Sprint velocity reached {eng['sprint_velocity']} points (+{eng['sprint_velocity'] - eng['sprint_velocity_prior']} MoM); "
            f"{eng['prs_merged_mtd']} PRs merged MTD with {eng['p1_incidents']} P1 incidents."
        )

        metrics = [
            MetricItem(
                label="Deploy Frequency / Week",
                value=str(eng["deployment_frequency_per_week"]),
                prior_value=str(eng["deployment_freq_prior"]),
                change_pct=dep_chg,
                direction="up" if dep_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="Lead Time (hrs)",
                value=str(eng["lead_time_hrs"]),
                prior_value=str(eng["lead_time_prior_hrs"]),
                change_pct=self._pct_change(eng["lead_time_hrs"], eng["lead_time_prior_hrs"]),
                direction="down",
                is_positive=False,
            ),
            MetricItem(
                label="Change Failure Rate",
                value=self._format_pct(eng["change_failure_rate"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=False,
            ),
            MetricItem(
                label="MTTR (hrs)",
                value=str(eng["mttr_hrs"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=False,
            ),
            MetricItem(
                label="Sprint Velocity",
                value=str(eng["sprint_velocity"]),
                prior_value=str(eng["sprint_velocity_prior"]),
                change_pct=vel_chg,
                direction="up" if vel_chg > 0 else "down",
                is_positive=True,
            ),
            MetricItem(
                label="Test Coverage",
                value=self._format_pct(eng["test_coverage"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=True,
            ),
            MetricItem(
                label="P1 Incidents (MTD)",
                value=str(eng["p1_incidents"]),
                prior_value=None,
                change_pct=None,
                direction="flat",
                is_positive=False,
            ),
        ]

        return ReportSection(
            section_id="engineering",
            title="Product & Engineering",
            narrative=narrative,
            metrics=metrics,
        )

    # ── Executive summary ──────────────────────────────────────────────────────

    def _build_executive_summary(self, dora_tier: str) -> str:
        rv = BOARD_METRICS["revenue"]
        fin = BOARD_METRICS["financials"]
        pl = BOARD_METRICS["pipeline"]
        cs = BOARD_METRICS["customer_success"]
        arr_chg = self._pct_change(rv["arr"], rv["arr_prior"])

        top_risk = STRATEGIC_RISKS[0]["risk"].lower()

        return (
            f"The company ended {BOARD_METRICS['period']} with "
            f"{self._format_currency(rv['arr'])} ARR ({arr_chg:+.1f}% MoM), "
            f"{rv['logo_count']} customers, and {fin['runway_months']} months of runway. "
            f"Net revenue retention of {self._format_pct(rv['nrr'] + 1.0)} and a declining "
            f"churn rate of {self._format_pct(cs['churn_rate_monthly'])} signal healthy customer health. "
            f"Pipeline coverage of {pl['pipeline_coverage']}x and an improving win rate of "
            f"{self._format_pct(pl['win_rate'])} position the business for continued growth. "
            f"Key risk for the board's attention: {top_risk}."
        )

    # ── DORA classification ────────────────────────────────────────────────────

    def _classify_dora(self) -> str:
        """
        Classify engineering against DORA tiers.

        Elite: deploy > 1/day (7/week), lead_time < 24h, cfr < 5%, mttr < 1h
        High:  deploy > 1/week, lead_time < 1 week (168h), cfr < 10%, mttr < 24h
        Medium: deploy > 1/month, lead_time < 1 month, cfr < 15%
        Low:   below Medium thresholds
        """
        eng = BOARD_METRICS["engineering"]
        dep = eng["deployment_frequency_per_week"]
        lt = eng["lead_time_hrs"]
        cfr = eng["change_failure_rate"]
        mttr = eng["mttr_hrs"]

        if dep > 7 and lt < 24 and cfr < 0.05 and mttr < 1:
            return "Elite"
        if dep > 1 and lt < 168 and cfr < 0.10 and mttr < 24:
            return "High"
        if dep > 0.25 and lt < 720 and cfr < 0.15:
            return "Medium"
        return "Low"

    # ── Formatting helpers ─────────────────────────────────────────────────────

    def _format_currency(self, v: float) -> str:
        """Format a dollar value as $8.42M, $342K, or $12K."""
        if abs(v) >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"${v / 1_000:.0f}K"
        return f"${v:.0f}"

    def _format_pct(self, v: float) -> str:
        """Format a float as a percentage string (e.g., 0.802 → '80.2%')."""
        return f"{v * 100:.1f}%"

    def _pct_change(self, current: float, prior: float) -> float:
        """Compute percentage change from prior to current."""
        if prior == 0:
            return 0.0
        return ((current - prior) / abs(prior)) * 100
