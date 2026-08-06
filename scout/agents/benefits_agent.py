"""
BenefitsAgent — Sprint 66

Handles employee benefits inquiries. Employees ask natural-language questions
like "How many PTO days do I have left?", "What's my 401k match?", or
"When does open enrollment start?" and the agent looks up their benefits
profile and returns a structured, actionable answer.

Business scenario:
  An employee emails HR: "I have 8 PTO days left — is that right?" or
  "Should I be contributing more to my 401k?" The agent looks up their
  benefits profile, classifies the question, and returns a precise answer
  with key facts, action items (if any), and the right contact for follow-up.

Question categories:
  pto_balance     — PTO days, vacation, time off
  health_insurance — health plan, medical, coverage, deductible, copay
  retirement_401k  — 401k, retirement, match, vesting, Fidelity
  open_enrollment  — open enrollment, change plan, benefits window
  general_benefits — everything else

Ownership: only returns data for the requesting employee email.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class BenefitsResult:
    employee_email: str
    employee_name: str
    department: str
    question_category: str          # pto_balance | health_insurance | retirement_401k | open_enrollment | general_benefits
    answer: str                     # natural-language answer
    key_facts: dict                 # structured facts for display
    action_items: list[str]         # smart insights / warnings
    contact: str                    # who to reach for follow-up


# ── Agent class ────────────────────────────────────────────────────────────────


class BenefitsAgent:
    """
    Autonomous employee benefits Q&A agent.

    Uses a mock employee roster (12 employees) for demo/dev. In production
    this would query the HRIS (Workday, BambooHR) and benefits provider APIs.
    Question classification is deterministic keyword matching — no LLM needed.
    """

    # ── Mock employee roster ───────────────────────────────────────────────────

    _MOCK_EMPLOYEES: list[dict] = [
        {
            "email": "sarah.chen@acme-corp.com",
            "name": "Sarah Chen",
            "department": "Engineering",
            "pto_remaining": 18,
            "pto_total": 20,
            "ytd_pto_used": 2,
            "health_plan": "premium_family",
            "k401_contrib_pct": 8,
            "k401_match_pct": 4,
            "start_date": "2021-03-15",
        },
        {
            "email": "james.rodriguez@acme-corp.com",
            "name": "James Rodriguez",
            "department": "Sales",
            "pto_remaining": 12,
            "pto_total": 15,
            "ytd_pto_used": 3,
            "health_plan": "standard_individual",
            "k401_contrib_pct": 6,
            "k401_match_pct": 4,
            "start_date": "2020-07-01",
        },
        {
            "email": "aisha.patel@acme-corp.com",
            "name": "Aisha Patel",
            "department": "Product",
            "pto_remaining": 8,
            "pto_total": 20,
            "ytd_pto_used": 12,
            "health_plan": "premium_individual",
            "k401_contrib_pct": 5,
            "k401_match_pct": 4,
            "start_date": "2022-01-10",
        },
        {
            "email": "marcus.johnson@acme-corp.com",
            "name": "Marcus Johnson",
            "department": "Engineering",
            "pto_remaining": 20,
            "pto_total": 20,
            "ytd_pto_used": 0,
            "health_plan": "standard_family",
            "k401_contrib_pct": 3,
            "k401_match_pct": 3,
            "start_date": "2023-05-20",
        },
        {
            "email": "elena.kovacs@acme-corp.com",
            "name": "Elena Kovacs",
            "department": "Finance",
            "pto_remaining": 5,
            "pto_total": 15,
            "ytd_pto_used": 10,
            "health_plan": "premium_family",
            "k401_contrib_pct": 10,
            "k401_match_pct": 4,
            "start_date": "2019-11-01",
        },
        {
            "email": "david.park@acme-corp.com",
            "name": "David Park",
            "department": "Engineering",
            "pto_remaining": 16,
            "pto_total": 20,
            "ytd_pto_used": 4,
            "health_plan": "premium_individual",
            "k401_contrib_pct": 0,
            "k401_match_pct": 0,
            "start_date": "2023-09-15",
        },
        {
            "email": "priya.sharma@acme-corp.com",
            "name": "Priya Sharma",
            "department": "Marketing",
            "pto_remaining": 11,
            "pto_total": 15,
            "ytd_pto_used": 4,
            "health_plan": "standard_individual",
            "k401_contrib_pct": 4,
            "k401_match_pct": 4,
            "start_date": "2021-08-20",
        },
        {
            "email": "tom.walsh@acme-corp.com",
            "name": "Tom Walsh",
            "department": "Sales",
            "pto_remaining": 0,
            "pto_total": 15,
            "ytd_pto_used": 15,
            "health_plan": "waived",
            "k401_contrib_pct": 0,
            "k401_match_pct": 0,
            "start_date": "2022-04-05",
        },
        {
            "email": "nina.lee@acme-corp.com",
            "name": "Nina Lee",
            "department": "HR",
            "pto_remaining": 14,
            "pto_total": 20,
            "ytd_pto_used": 6,
            "health_plan": "premium_family",
            "k401_contrib_pct": 6,
            "k401_match_pct": 4,
            "start_date": "2020-02-14",
        },
        {
            "email": "carlos.mendez@acme-corp.com",
            "name": "Carlos Mendez",
            "department": "Operations",
            "pto_remaining": 9,
            "pto_total": 15,
            "ytd_pto_used": 6,
            "health_plan": "standard_family",
            "k401_contrib_pct": 2,
            "k401_match_pct": 2,
            "start_date": "2022-10-31",
        },
        {
            "email": "yuki.tanaka@acme-corp.com",
            "name": "Yuki Tanaka",
            "department": "Engineering",
            "pto_remaining": 20,
            "pto_total": 20,
            "ytd_pto_used": 0,
            "health_plan": "premium_individual",
            "k401_contrib_pct": 8,
            "k401_match_pct": 4,
            "start_date": "2021-06-07",
        },
        {
            "email": "rachel.foster@acme-corp.com",
            "name": "Rachel Foster",
            "department": "Finance",
            "pto_remaining": 7,
            "pto_total": 15,
            "ytd_pto_used": 8,
            "health_plan": "standard_individual",
            "k401_contrib_pct": 5,
            "k401_match_pct": 4,
            "start_date": "2020-09-22",
        },
    ]

    # ── Health plan details ────────────────────────────────────────────────────

    _HEALTH_PLANS: dict[str, dict] = {
        "premium_family": {
            "plan_name": "Anthem Blue Cross PPO (Premium Family)",
            "provider": "Anthem Blue Cross",
            "monthly_contribution": "$350/mo",
            "deductible": "$500 individual / $1,500 family",
            "copay": "$20",
            "description": "Anthem Blue Cross PPO — $350/mo employee contribution, $500 individual deductible, $1,500 family deductible, $20 copay",
        },
        "premium_individual": {
            "plan_name": "Anthem Blue Cross PPO (Premium Individual)",
            "provider": "Anthem Blue Cross",
            "monthly_contribution": "$180/mo",
            "deductible": "$500",
            "copay": "$20",
            "description": "Anthem Blue Cross PPO — $180/mo employee contribution, $500 deductible, $20 copay",
        },
        "standard_family": {
            "plan_name": "UnitedHealth Choice Plus (Standard Family)",
            "provider": "UnitedHealth",
            "monthly_contribution": "$220/mo",
            "deductible": "$1,000 individual / $2,500 family",
            "copay": "$40",
            "description": "UnitedHealth Choice Plus — $220/mo employee contribution, $1,000 individual deductible, $2,500 family deductible, $40 copay",
        },
        "standard_individual": {
            "plan_name": "UnitedHealth Choice Plus (Standard Individual)",
            "provider": "UnitedHealth",
            "monthly_contribution": "$110/mo",
            "deductible": "$1,000",
            "copay": "$40",
            "description": "UnitedHealth Choice Plus — $110/mo employee contribution, $1,000 deductible, $40 copay",
        },
        "waived": {
            "plan_name": "No coverage (waived)",
            "provider": "N/A",
            "monthly_contribution": "$0/mo",
            "deductible": "N/A",
            "copay": "N/A",
            "description": "No health coverage elected. May re-enroll during open enrollment (Nov 1-30) or qualifying life event.",
        },
    }

    # ── 401k policy ────────────────────────────────────────────────────────────

    _K401_POLICY = {
        "provider": "Fidelity NetBenefits",
        "portal": "fidelity.com/netbenefits",
        "phone": "1-800-835-5097",
        "match_description": "100% of first 4% of salary contributed",
        "vesting": "3-year cliff vesting for employer match",
        "limit_under_50": "$23,000",
        "limit_50_plus": "$30,500",
    }

    # ── PTO policy ─────────────────────────────────────────────────────────────

    _PTO_POLICY = {
        "tier_0_2_years": 15,          # days/year for 0-2 years tenure
        "tier_2_plus_years": 20,       # days/year for 2+ years tenure
        "accrual_0_2": "1.25 days/month",
        "accrual_2_plus": "1.67 days/month",
        "rollover_max": 5,             # max days that roll over
        "sick_leave": 10,              # separate, not tracked here
    }

    # ── Open enrollment ────────────────────────────────────────────────────────

    _ENROLLMENT_POLICY = {
        "window": "November 1–30",
        "effective_date": "January 1 of the following year",
        "qualifying_event_window": "30 days",
        "qualifying_events": "marriage, birth, divorce, loss of other coverage",
    }

    # ── Contact routing ────────────────────────────────────────────────────────

    _CONTACTS: dict[str, str] = {
        "pto_balance": "Your manager or HR at hr@company.com",
        "health_insurance": "Benefits team at benefits@company.com or (800) 555-0192",
        "retirement_401k": "Fidelity NetBenefits at 1-800-835-5097 or fidelity.com/netbenefits",
        "open_enrollment": "Benefits team at benefits@company.com",
        "general_benefits": "HR at hr@company.com",
    }

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_benefits(
        self, employee_email: str, question: str, tenant_id: str, db
    ) -> BenefitsResult:
        """
        Look up an employee's benefits and answer their specific question.

        Classifies the question, retrieves the correct facts, generates
        a natural-language answer, computes action items, and routes to
        the right contact. Only returns data for the requesting employee.
        """
        profile = self._find_employee(employee_email)
        if profile is None:
            logger.warning(
                "BenefitsAgent get_benefits email=%s tenant=%s NOT_FOUND",
                employee_email,
                tenant_id,
            )
            return self._not_found_result(employee_email, question)

        category = self._classify_question(question)
        logger.info(
            "BenefitsAgent get_benefits email=%s tenant=%s category=%s",
            employee_email,
            tenant_id,
            category,
        )

        answer = self._build_answer(category, profile)
        key_facts = self._build_key_facts(category, profile)
        action_items = self._build_action_items(profile)
        contact = self._CONTACTS[category]

        return BenefitsResult(
            employee_email=employee_email,
            employee_name=profile["name"],
            department=profile["department"],
            question_category=category,
            answer=answer,
            key_facts=key_facts,
            action_items=action_items,
            contact=contact,
        )

    def get_summary(
        self, employee_email: str, tenant_id: str, db
    ) -> dict:
        """
        Return a full benefits snapshot for the Benefits Snapshot card.

        All categories in one call — used by the right panel of the UI.
        Only returns data for the requesting employee.
        """
        profile = self._find_employee(employee_email)
        if profile is None:
            return {"found": False, "employee_email": employee_email}

        plan = self._HEALTH_PLANS.get(profile["health_plan"], self._HEALTH_PLANS["waived"])
        contrib = profile["k401_contrib_pct"]
        match_cap = min(contrib, 4)  # company matches up to 4%

        return {
            "found": True,
            "employee_name": profile["name"],
            "department": profile["department"],
            "pto_remaining": profile["pto_remaining"],
            "pto_total": profile["pto_total"],
            "ytd_pto_used": profile["ytd_pto_used"],
            "health_plan": plan["plan_name"],
            "monthly_contribution": plan["monthly_contribution"],
            "contrib_pct": contrib,
            "match_pct": match_cap,
            "match_captured": contrib >= 4,
            "enrollment_window": self._ENROLLMENT_POLICY["window"],
        }

    # ── Classification ─────────────────────────────────────────────────────────

    def _classify_question(self, question: str) -> str:
        """
        Classify a free-text question into one of the five benefit categories.

        Uses ordered keyword matching. First match wins.
        Returns 'general_benefits' if no keywords match.
        """
        q = question.lower()

        pto_keywords = ["pto", "vacation", "time off", "days off", "days left",
                        "days remaining", "holiday", "leave balance", "how many days"]
        health_keywords = ["health", "medical", "insurance", "coverage", "deductible",
                           "copay", "co-pay", "plan", "anthem", "united", "doctor",
                           "prescription"]
        k401_keywords = ["401k", "401(k)", "retirement", "match", "vesting", "fidelity",
                         "contribute", "contribution", "netbenefits"]
        enrollment_keywords = ["open enrollment", "enroll", "change plan", "change my plan",
                               "benefits window", "qualifying", "life event"]

        for kw in pto_keywords:
            if kw in q:
                return "pto_balance"

        for kw in enrollment_keywords:
            if kw in q:
                return "open_enrollment"

        for kw in k401_keywords:
            if kw in q:
                return "retirement_401k"

        for kw in health_keywords:
            if kw in q:
                return "health_insurance"

        return "general_benefits"

    # ── Answer builders ────────────────────────────────────────────────────────

    def _build_answer(self, category: str, profile: dict) -> str:
        """Dispatch to the appropriate answer builder by category."""
        if category == "pto_balance":
            return self._get_pto_answer(profile)
        if category == "health_insurance":
            return self._get_health_answer(profile)
        if category == "retirement_401k":
            return self._get_401k_answer(profile)
        if category == "open_enrollment":
            return self._get_enrollment_answer()
        return self._get_general_answer(profile)

    def _get_pto_answer(self, profile: dict) -> str:
        remaining = profile["pto_remaining"]
        total = profile["pto_total"]
        used = profile["ytd_pto_used"]
        name = profile["name"].split()[0]

        if remaining == 0:
            return (
                f"{name}, you have used all {total} of your PTO days this year "
                f"({used} days used year-to-date). You have no remaining PTO balance. "
                "Please speak with your manager before scheduling any additional time off."
            )
        if remaining > 15:
            return (
                f"{name}, you have {remaining} PTO days remaining out of your {total}-day annual allotment "
                f"({used} days used year-to-date). Note that per company policy, only 5 days roll over "
                "to the next year — any unused days above 5 will forfeit on December 31."
            )
        return (
            f"{name}, you have {remaining} PTO days remaining out of your {total}-day annual allotment "
            f"({used} days used year-to-date). PTO accrues monthly and unused days above 5 forfeit at year-end."
        )

    def _get_health_answer(self, profile: dict) -> str:
        plan_key = profile["health_plan"]
        plan = self._HEALTH_PLANS.get(plan_key, self._HEALTH_PLANS["waived"])
        name = profile["name"].split()[0]

        if plan_key == "waived":
            return (
                f"{name}, you have waived health coverage. You are currently not enrolled in a "
                "company health plan. You can enroll during the next open enrollment window "
                "(November 1–30) or within 30 days of a qualifying life event such as marriage, "
                "birth, divorce, or loss of other coverage."
            )
        return (
            f"{name}, you are enrolled in the {plan['plan_name']} plan. "
            f"Your monthly contribution is {plan['monthly_contribution']}. "
            f"Your deductible is {plan['deductible']} and your copay is {plan['copay']}. "
            f"Coverage is provided through {plan['provider']}."
        )

    def _get_401k_answer(self, profile: dict) -> str:
        contrib = profile["k401_contrib_pct"]
        matched = min(contrib, 4)
        name = profile["name"].split()[0]
        policy = self._K401_POLICY

        if contrib == 0:
            return (
                f"{name}, you are not currently contributing to your 401k. "
                "The company matches 100% of the first 4% of salary you contribute — "
                "by not contributing, you are leaving the full employer match on the table. "
                f"To enroll or change your contribution, visit {policy['portal']} or "
                f"call Fidelity at {policy['phone']}."
            )
        if contrib < 4:
            leave = 4 - contrib
            return (
                f"{name}, you are contributing {contrib}% of your salary to your 401k. "
                f"The company matches 100% of the first 4% contributed, so you are currently receiving "
                f"a {matched}% employer match. You are leaving {leave}% in uncaptured match by not "
                f"contributing at least 4%. Visit {policy['portal']} to adjust your contribution."
            )
        if contrib == 4:
            return (
                f"{name}, you are contributing {contrib}% of your salary to your 401k — exactly "
                "at the threshold to receive the full 4% employer match. "
                f"Your 401k is administered by Fidelity NetBenefits ({policy['portal']}). "
                f"Vesting on employer contributions follows a 3-year cliff schedule."
            )
        return (
            f"{name}, you are contributing {contrib}% of your salary to your 401k, "
            "which exceeds the 4% threshold needed for the full employer match — great work! "
            f"Your total match received is 4% of salary. Plan administration: {policy['portal']}. "
            f"2024 contribution limit: {policy['limit_under_50']} (under 50) or "
            f"{policy['limit_50_plus']} (age 50+)."
        )

    def _get_enrollment_answer(self) -> str:
        ep = self._ENROLLMENT_POLICY
        return (
            f"Open enrollment runs annually from {ep['window']}. "
            f"Changes made during open enrollment take effect {ep['effective_date']}. "
            f"Outside of open enrollment, you can make changes within {ep['qualifying_event_window']} "
            f"of a qualifying life event ({ep['qualifying_events']}). "
            "Contact benefits@company.com for assistance with your enrollment choices."
        )

    def _get_general_answer(self, profile: dict) -> str:
        plan = self._HEALTH_PLANS.get(profile["health_plan"], self._HEALTH_PLANS["waived"])
        name = profile["name"].split()[0]
        contrib = profile["k401_contrib_pct"]
        return (
            f"{name}, here is a summary of your current benefits: "
            f"PTO balance: {profile['pto_remaining']} of {profile['pto_total']} days remaining. "
            f"Health plan: {plan['plan_name']} ({plan['monthly_contribution']}). "
            f"401k contribution: {contrib}% (company matches up to 4%). "
            "Open enrollment: November 1–30 annually. "
            "For detailed benefit questions, contact hr@company.com."
        )

    # ── Key facts ──────────────────────────────────────────────────────────────

    def _build_key_facts(self, category: str, profile: dict) -> dict:
        """Build category-specific key facts dict for the UI data grid."""
        if category == "pto_balance":
            total = profile["pto_total"]
            accrual = "1.67 days/month" if total == 20 else "1.25 days/month"
            return {
                "pto_remaining": profile["pto_remaining"],
                "pto_total": total,
                "ytd_used": profile["ytd_pto_used"],
                "accrual_rate": accrual,
            }

        if category == "health_insurance":
            plan = self._HEALTH_PLANS.get(profile["health_plan"], self._HEALTH_PLANS["waived"])
            return {
                "plan_name": plan["plan_name"],
                "monthly_contribution": plan["monthly_contribution"],
                "deductible": plan["deductible"],
                "copay": plan["copay"],
            }

        if category == "retirement_401k":
            contrib = profile["k401_contrib_pct"]
            return {
                "contribution_pct": contrib,
                "match_pct": min(contrib, 4),
                "match_captured": contrib >= 4,
                "provider": self._K401_POLICY["provider"],
                "portal": self._K401_POLICY["portal"],
            }

        if category == "open_enrollment":
            plan = self._HEALTH_PLANS.get(profile["health_plan"], self._HEALTH_PLANS["waived"])
            return {
                "window": self._ENROLLMENT_POLICY["window"],
                "effective_date": self._ENROLLMENT_POLICY["effective_date"],
                "current_plan": plan["plan_name"],
            }

        # general_benefits
        plan = self._HEALTH_PLANS.get(profile["health_plan"], self._HEALTH_PLANS["waived"])
        return {
            "pto_remaining": profile["pto_remaining"],
            "health_plan": plan["plan_name"],
            "k401_contribution_pct": profile["k401_contrib_pct"],
            "enrollment_window": self._ENROLLMENT_POLICY["window"],
        }

    # ── Action items ───────────────────────────────────────────────────────────

    def _build_action_items(self, profile: dict) -> list[str]:
        """
        Generate smart insight action items based on the employee's benefits profile.

        Checks all categories regardless of the question asked — surface any
        noteworthy situations the employee should know about.
        """
        items: list[str] = []

        contrib = profile["k401_contrib_pct"]
        if contrib < 4:
            if contrib == 0:
                items.append(
                    "You are not contributing to your 401k. Enrolling at 4% captures the full "
                    "employer match — effectively a 4% salary increase."
                )
            else:
                leave = 4 - contrib
                items.append(
                    f"You're leaving employer match on the table. Increasing from {contrib}% to 4% "
                    f"captures an additional {leave}% employer match at no extra cost to you."
                )

        pto_remaining = profile["pto_remaining"]
        if pto_remaining == 0:
            items.append(
                "You've used all your PTO for the year. Speak with your manager before "
                "scheduling additional time off."
            )
        elif pto_remaining > 15:
            items.append(
                f"You have a high PTO balance ({pto_remaining} days). Per policy, only 5 days "
                "roll over — consider scheduling time off before December 31."
            )

        if profile["health_plan"] == "waived":
            items.append(
                "You currently have no health coverage. You can enroll during open enrollment "
                "(Nov 1-30) or after a qualifying life event."
            )

        return items

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _find_employee(self, email: str) -> dict | None:
        """Look up an employee by email (case-insensitive). Returns None if not found."""
        target = email.lower().strip()
        for emp in self._MOCK_EMPLOYEES:
            if emp["email"].lower() == target:
                return emp
        return None

    def _not_found_result(self, employee_email: str, question: str) -> BenefitsResult:
        """Return a graceful not-found result rather than raising."""
        category = self._classify_question(question)
        return BenefitsResult(
            employee_email=employee_email,
            employee_name="Unknown",
            department="Unknown",
            question_category=category,
            answer=(
                f"No benefits profile was found for {employee_email}. "
                "Please verify your email address or contact HR at hr@company.com "
                "if you believe this is an error."
            ),
            key_facts={},
            action_items=[],
            contact="HR at hr@company.com",
        )
