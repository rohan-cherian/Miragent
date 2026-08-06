"""
PayrollDocumentAgent — Sprint 61

Employee self-service agent for retrieving payroll documents.
An employee submits a request (document type + period) and the agent:
  1. Looks up the employee in the connected payroll system (ADP/Workday/Rippling)
  2. Retrieves the requested document
  3. Returns structured document data for display and download
  4. Logs the retrieval to the audit trail

Supported document types:
  w2     — W-2 Wage and Tax Statement (annual, by year)
  paystub — Pay Stub (by pay date or "latest")
  1099   — 1099-NEC (annual, by year, for contractors)
  ytd    — Year-to-Date Earnings Summary (current year)

Data source: ADP / Workday / Rippling connector (mock in dev).
Auth boundary: the requesting user can only retrieve their own documents.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── SS wage base (2023/2024/2025 value) ───────────────────────────────────────
SS_WAGE_BASE = 160_200.0

# ── Employer constants ────────────────────────────────────────────────────────
EMPLOYER_NAME = "Acme Corporation"
EMPLOYER_EIN = "47-1234567"
EMPLOYER_ADDRESS = "123 Innovation Drive, San Francisco, CA 94105"


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class PayrollEmployee:
    email: str
    full_name: str
    employee_id: str
    department: str
    title: str
    pay_type: str           # "salary" or "hourly"
    annual_salary: float
    hourly_rate: float      # 0 if salaried
    hire_date: str          # ISO date
    filing_status: str      # "single", "married", etc.
    allowances: int
    state: str              # e.g. "CA"
    employer_name: str
    employer_ein: str       # e.g. "47-1234567"


@dataclass
class PayrollDocumentResult:
    request_id: str
    employee_email: str
    document_type: str
    period: str
    status: str             # "delivered" / "not_found" / "error"
    document: Optional[dict]
    error: Optional[str]
    completed_at: datetime


# ── Mock employee roster ──────────────────────────────────────────────────────

_MOCK_EMPLOYEES: list[dict] = [
    {
        "email": "s.chen@acmecorp.com",
        "full_name": "Sarah Chen",
        "employee_id": "EMP-001",
        "department": "Engineering",
        "title": "Senior Software Engineer",
        "pay_type": "salary",
        "annual_salary": 145_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2020-03-15",
        "filing_status": "single",
        "allowances": 1,
        "state": "CA",
    },
    {
        "email": "m.johnson@acmecorp.com",
        "full_name": "Marcus Johnson",
        "employee_id": "EMP-002",
        "department": "Sales",
        "title": "Account Executive",
        "pay_type": "salary",
        "annual_salary": 85_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2019-07-01",
        "filing_status": "married",
        "allowances": 3,
        "state": "TX",
    },
    {
        "email": "p.patel@acmecorp.com",
        "full_name": "Priya Patel",
        "employee_id": "EMP-003",
        "department": "Marketing",
        "title": "Marketing Manager",
        "pay_type": "salary",
        "annual_salary": 95_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2021-01-10",
        "filing_status": "married",
        "allowances": 2,
        "state": "NY",
    },
    {
        "email": "j.liu@acmecorp.com",
        "full_name": "James Liu",
        "employee_id": "EMP-004",
        "department": "Finance",
        "title": "Financial Analyst",
        "pay_type": "salary",
        "annual_salary": 110_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2018-09-22",
        "filing_status": "married",
        "allowances": 2,
        "state": "CA",
    },
    {
        "email": "e.vasquez@acmecorp.com",
        "full_name": "Elena Vasquez",
        "employee_id": "EMP-005",
        "department": "HR",
        "title": "HR Business Partner",
        "pay_type": "salary",
        "annual_salary": 90_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2020-11-03",
        "filing_status": "single",
        "allowances": 1,
        "state": "CA",
    },
    {
        "email": "t.brennan@acmecorp.com",
        "full_name": "Tom Brennan",
        "employee_id": "EMP-006",
        "department": "Engineering",
        "title": "Staff Engineer",
        "pay_type": "salary",
        "annual_salary": 130_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2017-06-12",
        "filing_status": "married",
        "allowances": 4,
        "state": "WA",
    },
    {
        "email": "r.mendez@acmecorp.com",
        "full_name": "Rosa Mendez",
        "employee_id": "EMP-007",
        "department": "Customer Success",
        "title": "Customer Success Manager",
        "pay_type": "salary",
        "annual_salary": 80_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2022-02-14",
        "filing_status": "single",
        "allowances": 1,
        "state": "FL",
    },
    {
        "email": "d.kim@acmecorp.com",
        "full_name": "David Kim",
        "employee_id": "EMP-008",
        "department": "Product",
        "title": "Senior Product Manager",
        "pay_type": "salary",
        "annual_salary": 125_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2019-04-08",
        "filing_status": "married",
        "allowances": 2,
        "state": "CA",
    },
    {
        "email": "a.nguyen@acmecorp.com",
        "full_name": "Amy Nguyen",
        "employee_id": "EMP-009",
        "department": "Engineering",
        "title": "DevOps Engineer",
        "pay_type": "salary",
        "annual_salary": 120_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2021-08-23",
        "filing_status": "single",
        "allowances": 1,
        "state": "OR",
    },
    {
        "email": "c.rodriguez@acmecorp.com",
        "full_name": "Carlos Rodriguez",
        "employee_id": "EMP-010",
        "department": "Sales",
        "title": "Sales Development Representative",
        "pay_type": "hourly",
        "annual_salary": 52_000.0,
        "hourly_rate": 25.0,
        "hire_date": "2023-03-06",
        "filing_status": "single",
        "allowances": 1,
        "state": "TX",
    },
    {
        "email": "l.park@acmecorp.com",
        "full_name": "Lauren Park",
        "employee_id": "EMP-011",
        "department": "Design",
        "title": "UX Designer",
        "pay_type": "salary",
        "annual_salary": 105_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2020-07-20",
        "filing_status": "married",
        "allowances": 2,
        "state": "CA",
    },
    {
        "email": "b.wilson@acmecorp.com",
        "full_name": "Brian Wilson",
        "employee_id": "EMP-012",
        "department": "Legal",
        "title": "General Counsel",
        "pay_type": "salary",
        "annual_salary": 175_000.0,
        "hourly_rate": 0.0,
        "hire_date": "2016-11-01",
        "filing_status": "married",
        "allowances": 3,
        "state": "NY",
    },
]

# Build lookup index
_EMAIL_INDEX: dict[str, dict] = {e["email"]: e for e in _MOCK_EMPLOYEES}


# ── Agent class ───────────────────────────────────────────────────────────────


class PayrollDocumentAgent:
    """
    Self-service payroll document retrieval agent.

    Looks up the employee in the payroll system (mock in dev), generates the
    requested document, and returns a PayrollDocumentResult. If the email is
    not in the mock roster, a plausible employee record is synthesized from
    the email so the agent remains demoable for any login.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        employee_email: str,
        document_type: str,
        period: str,
        tenant_id: str,
        request_id: str,
    ) -> PayrollDocumentResult:
        """Generate a payroll document for the requesting employee."""
        employee = self._lookup_employee(employee_email, tenant_id)

        if not employee:
            return PayrollDocumentResult(
                request_id=request_id,
                employee_email=employee_email,
                document_type=document_type,
                period=period,
                status="not_found",
                document=None,
                error=f"No payroll record found for {employee_email}",
                completed_at=datetime.now(timezone.utc),
            )

        try:
            doc = self._generate_document(employee, document_type, period)
            return PayrollDocumentResult(
                request_id=request_id,
                employee_email=employee_email,
                document_type=document_type,
                period=period,
                status="delivered",
                document=doc,
                error=None,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error("PayrollDocumentAgent error for %s: %s", employee_email, exc)
            return PayrollDocumentResult(
                request_id=request_id,
                employee_email=employee_email,
                document_type=document_type,
                period=period,
                status="error",
                document=None,
                error=str(exc),
                completed_at=datetime.now(timezone.utc),
            )

    # ── Employee lookup ───────────────────────────────────────────────────────

    def _lookup_employee(
        self, email: str, tenant_id: str
    ) -> Optional[PayrollEmployee]:
        """
        Try the mock roster by email.
        If not found, synthesize a deterministic employee from the email
        so the agent remains fully demoable for any registered user.
        """
        # 1. Exact roster match
        if email in _EMAIL_INDEX:
            raw = _EMAIL_INDEX[email]
            return PayrollEmployee(
                email=email,
                full_name=raw["full_name"],
                employee_id=raw["employee_id"],
                department=raw["department"],
                title=raw["title"],
                pay_type=raw["pay_type"],
                annual_salary=raw["annual_salary"],
                hourly_rate=raw["hourly_rate"],
                hire_date=raw["hire_date"],
                filing_status=raw["filing_status"],
                allowances=raw["allowances"],
                state=raw["state"],
                employer_name=EMPLOYER_NAME,
                employer_ein=EMPLOYER_EIN,
            )

        # 2. Synthesize a plausible employee from the email (for demo purposes)
        return self._synthesize_employee(email, tenant_id)

    def _synthesize_employee(self, email: str, tenant_id: str) -> PayrollEmployee:
        """
        Build a deterministic but plausible employee record for any email.
        Uses a hash of the email to seed salary / department choices so
        the same email always gets the same document.
        """
        h = int(hashlib.md5(email.encode()).hexdigest(), 16)

        local = email.split("@")[0]
        parts = local.replace(".", " ").replace("_", " ").split()
        first = parts[0].capitalize() if parts else "Employee"
        last = parts[1].capitalize() if len(parts) > 1 else "User"
        full_name = f"{first} {last}"

        departments = ["Engineering", "Sales", "Marketing", "Finance", "Product", "HR"]
        titles = [
            "Software Engineer",
            "Account Executive",
            "Marketing Specialist",
            "Financial Analyst",
            "Product Manager",
            "HR Specialist",
        ]
        states = ["CA", "NY", "TX", "WA", "FL", "OR"]
        salaries = [75_000, 90_000, 105_000, 120_000, 135_000, 150_000]
        filing_statuses = ["single", "married", "single", "single", "married", "married"]

        idx = h % len(departments)
        emp_num = (h % 9000) + 1000

        return PayrollEmployee(
            email=email,
            full_name=full_name,
            employee_id=f"EMP-{emp_num}",
            department=departments[idx],
            title=titles[idx],
            pay_type="salary",
            annual_salary=float(salaries[idx]),
            hourly_rate=0.0,
            hire_date=f"{2018 + (h % 6)}-{(h % 12) + 1:02d}-01",
            filing_status=filing_statuses[idx],
            allowances=(h % 3) + 1,
            state=states[idx],
            employer_name=EMPLOYER_NAME,
            employer_ein=EMPLOYER_EIN,
        )

    # ── Document dispatch ─────────────────────────────────────────────────────

    def _generate_document(
        self, employee: PayrollEmployee, doc_type: str, period: str
    ) -> dict:
        if doc_type == "w2":
            return self._generate_w2(employee, period)
        if doc_type == "paystub":
            return self._generate_paystub(employee, period)
        if doc_type == "1099":
            return self._generate_1099(employee, period)
        if doc_type == "ytd":
            return self._generate_ytd(employee, period)
        raise ValueError(f"Unknown document type: {doc_type}")

    # ── W-2 ───────────────────────────────────────────────────────────────────

    def _generate_w2(self, employee: PayrollEmployee, period: str) -> dict:
        """Generate a W-2 dict matching the real IRS W-2 box layout."""
        tax_year = int(period) if period.isdigit() else datetime.now().year

        annual_salary = employee.annual_salary
        k401_contribution = round(annual_salary * 0.06, 2)        # Box 12a: 6% 401k
        health_premium = 3_600.0                                    # Box 12b: $3,600/yr pre-tax

        # Box 1: Federal wages = salary minus pre-tax deductions
        box1_wages = round(annual_salary - k401_contribution - health_premium, 2)

        # Box 2: Federal income tax withheld (~22%)
        box2_fed_tax = round(box1_wages * 0.22, 2)

        # Box 3: Social Security wages (capped at SS wage base)
        box3_ss_wages = round(min(box1_wages, SS_WAGE_BASE), 2)

        # Box 4: SS tax withheld
        box4_ss_tax = round(box3_ss_wages * 0.062, 2)

        # Box 5: Medicare wages (no cap)
        box5_medicare_wages = box1_wages

        # Box 6: Medicare tax withheld
        box6_medicare_tax = round(box5_medicare_wages * 0.0145, 2)

        # Box 16: State wages = same as federal
        box16_state_wages = box1_wages

        # Box 17: State income tax (~40% of federal)
        box17_state_tax = round(box2_fed_tax * 0.40, 2)

        return {
            "document_type": "w2",
            "tax_year": tax_year,
            "form_title": f"W-2 Wage and Tax Statement {tax_year}",
            "employer": {
                "name": employee.employer_name,
                "ein": employee.employer_ein,
                "address": EMPLOYER_ADDRESS,
            },
            "employee": {
                "name": employee.full_name,
                "email": employee.email,
                "employee_id": employee.employee_id,
                "ssn_last4": "XXXX",  # masked
                "address": f"[On file] {employee.state}",
            },
            # Core wage and tax boxes
            "box_1_wages": box1_wages,
            "box_2_federal_tax": box2_fed_tax,
            "box_3_ss_wages": box3_ss_wages,
            "box_4_ss_tax": box4_ss_tax,
            "box_5_medicare_wages": box5_medicare_wages,
            "box_6_medicare_tax": box6_medicare_tax,
            "box_7_ss_tips": 0.0,
            "box_8_allocated_tips": 0.0,
            "box_10_dependent_care": 0.0,
            "box_11_nonqualified_plans": 0.0,
            "box_12a_code": "D",
            "box_12a_amount": k401_contribution,
            "box_12b_code": "DD",
            "box_12b_amount": 9_000.0,   # employer-sponsored health (DD = total cost)
            "box_13_statutory_employee": False,
            "box_13_retirement_plan": True,
            "box_13_third_party_sick": False,
            "box_14_other": {},
            "box_15_state": employee.state,
            "box_15_employer_state_id": f"{employee.state}-{employee.employer_ein}",
            "box_16_state_wages": box16_state_wages,
            "box_17_state_income_tax": box17_state_tax,
            "box_18_local_wages": 0.0,
            "box_19_local_tax": 0.0,
            "box_20_locality_name": "",
        }

    # ── Paystub ───────────────────────────────────────────────────────────────

    def _generate_paystub(self, employee: PayrollEmployee, period: str) -> dict:
        """
        Generate a bi-weekly paystub.

        period: "latest" or an ISO date string like "2026-05-01"
        """
        today = date.today()

        if period == "latest":
            # Find the most recent completed bi-weekly pay period
            # Anchor: Jan 1 of current year, pay days every 14 days
            anchor = date(today.year, 1, 3)  # first Friday of year (approx)
            days_since = (today - anchor).days
            completed_periods = days_since // 14
            pay_date = anchor + timedelta(days=completed_periods * 14)
            if pay_date >= today:
                pay_date -= timedelta(days=14)
        else:
            pay_date = date.fromisoformat(period)

        pay_period_end = pay_date - timedelta(days=1)
        pay_period_start = pay_period_end - timedelta(days=13)

        # Which paycheck number in the year? (biweekly = 26 per year)
        year_start = date(pay_date.year, 1, 1)
        days_into_year = (pay_date - year_start).days
        paycheck_number = max(1, days_into_year // 14)

        annual_salary = employee.annual_salary
        biweekly_gross = round(annual_salary / 26, 2)

        # Deductions (per paycheck)
        federal_tax = round(biweekly_gross * 0.22, 2)
        state_tax = round(biweekly_gross * 0.06, 2)
        ss_tax = round(biweekly_gross * 0.062, 2)
        medicare_tax = round(biweekly_gross * 0.0145, 2)
        health_insurance = 150.00
        dental = 25.00
        vision = 8.00
        k401 = round(biweekly_gross * 0.06, 2)

        total_deductions = round(
            federal_tax + state_tax + ss_tax + medicare_tax
            + health_insurance + dental + vision + k401,
            2,
        )
        net_pay = round(biweekly_gross - total_deductions, 2)

        # YTD (approximate: multiply by period number)
        ytd_gross = round(biweekly_gross * paycheck_number, 2)
        ytd_federal = round(federal_tax * paycheck_number, 2)
        ytd_state = round(state_tax * paycheck_number, 2)
        ytd_ss = round(ss_tax * paycheck_number, 2)
        ytd_medicare = round(medicare_tax * paycheck_number, 2)
        ytd_health = round(health_insurance * paycheck_number, 2)
        ytd_dental = round(dental * paycheck_number, 2)
        ytd_vision = round(vision * paycheck_number, 2)
        ytd_k401 = round(k401 * paycheck_number, 2)
        ytd_deductions = round(
            ytd_federal + ytd_state + ytd_ss + ytd_medicare
            + ytd_health + ytd_dental + ytd_vision + ytd_k401,
            2,
        )
        ytd_net = round(ytd_gross - ytd_deductions, 2)

        earnings: dict = {"regular": biweekly_gross, "overtime": 0.0, "gross": biweekly_gross}
        if employee.pay_type == "hourly":
            hours = 80  # standard 2-week period
            rate = employee.hourly_rate
            earnings = {
                "regular_hours": hours,
                "regular_rate": rate,
                "regular": round(hours * rate, 2),
                "overtime_hours": 0,
                "overtime_rate": round(rate * 1.5, 2),
                "overtime": 0.0,
                "gross": round(hours * rate, 2),
            }

        return {
            "document_type": "paystub",
            "form_title": "Earnings Statement",
            "pay_stub_number": paycheck_number,
            "pay_date": pay_date.isoformat(),
            "pay_period_start": pay_period_start.isoformat(),
            "pay_period_end": pay_period_end.isoformat(),
            "employer": {
                "name": employee.employer_name,
                "ein": employee.employer_ein,
                "address": EMPLOYER_ADDRESS,
            },
            "employee": {
                "name": employee.full_name,
                "email": employee.email,
                "employee_id": employee.employee_id,
                "department": employee.department,
                "title": employee.title,
                "pay_type": employee.pay_type,
                "filing_status": employee.filing_status,
                "allowances": employee.allowances,
                "state": employee.state,
            },
            "earnings": earnings,
            "deductions": {
                "federal_income_tax": federal_tax,
                "state_income_tax": state_tax,
                "social_security_tax": ss_tax,
                "medicare_tax": medicare_tax,
                "health_insurance": health_insurance,
                "dental": dental,
                "vision": vision,
                "401k_contribution": k401,
                "total": total_deductions,
            },
            "net_pay": net_pay,
            "ytd": {
                "gross": ytd_gross,
                "federal_income_tax": ytd_federal,
                "state_income_tax": ytd_state,
                "social_security_tax": ytd_ss,
                "medicare_tax": ytd_medicare,
                "health_insurance": ytd_health,
                "dental": ytd_dental,
                "vision": ytd_vision,
                "401k_contribution": ytd_k401,
                "total_deductions": ytd_deductions,
                "net": ytd_net,
            },
        }

    # ── 1099-NEC ──────────────────────────────────────────────────────────────

    def _generate_1099(self, employee: PayrollEmployee, period: str) -> dict:
        """Generate a 1099-NEC for a contractor. No tax withholding boxes."""
        tax_year = int(period) if period.isdigit() else datetime.now().year
        nonemployee_comp = employee.annual_salary  # full pay, no withholding

        return {
            "document_type": "1099",
            "tax_year": tax_year,
            "form_title": f"1099-NEC Nonemployee Compensation {tax_year}",
            "payer": {
                "name": employee.employer_name,
                "ein": employee.employer_ein,
                "address": EMPLOYER_ADDRESS,
            },
            "recipient": {
                "name": employee.full_name,
                "email": employee.email,
                "tin_last4": "XXXX",  # masked
                "address": f"[On file] {employee.state}",
            },
            # 1099-NEC has very few boxes
            "box_1_nonemployee_compensation": round(nonemployee_comp, 2),
            "box_4_federal_tax_withheld": 0.0,   # contractors pay their own taxes
            "box_5_state_tax_withheld": 0.0,
            "box_6_state": employee.state,
            "box_7_payer_state_id": f"{employee.state}-{employee.employer_ein}",
            "note": (
                "As a contractor, you are responsible for self-employment tax "
                "(15.3% on net earnings up to SS wage base + 2.9% Medicare on all earnings). "
                "Quarterly estimated tax payments may be required."
            ),
        }

    # ── Year-to-Date ──────────────────────────────────────────────────────────

    def _generate_ytd(self, employee: PayrollEmployee, period: str) -> dict:
        """
        Generate a YTD earnings summary through the current month.
        Returns a month-by-month breakdown plus running totals.
        """
        today = date.today()
        current_year = today.year
        current_month = today.month

        annual_salary = employee.annual_salary
        biweekly_gross = annual_salary / 26
        # Approximate monthly gross (some months have 2 paychecks, some 3)
        monthly_gross = annual_salary / 12

        months_data = []
        running_gross = 0.0
        running_fed = 0.0
        running_state = 0.0
        running_ss = 0.0
        running_medicare = 0.0
        running_k401 = 0.0
        running_health = 0.0
        running_net = 0.0

        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]

        for m in range(1, current_month + 1):
            gross = round(monthly_gross, 2)

            # Deductions
            fed = round(gross * 0.22, 2)
            state = round(gross * 0.06, 2)
            # SS cap check (approximate monthly)
            ytd_before = running_gross
            ss_eligible = min(gross, max(0, SS_WAGE_BASE - ytd_before))
            ss = round(ss_eligible * 0.062, 2)
            medicare = round(gross * 0.0145, 2)
            health = round(150.0 * 2 if m % 2 == 0 else 150.0, 2)  # ~2 paychecks/month
            health = 300.0  # simplify: $300/month
            k401 = round(gross * 0.06, 2)

            total_ded = round(fed + state + ss + medicare + health + k401, 2)
            net = round(gross - total_ded, 2)

            running_gross = round(running_gross + gross, 2)
            running_fed = round(running_fed + fed, 2)
            running_state = round(running_state + state, 2)
            running_ss = round(running_ss + ss, 2)
            running_medicare = round(running_medicare + medicare, 2)
            running_k401 = round(running_k401 + k401, 2)
            running_health = round(running_health + health, 2)
            running_net = round(running_net + net, 2)

            months_data.append({
                "month": month_names[m - 1],
                "month_number": m,
                "gross": gross,
                "federal_tax": fed,
                "state_tax": state,
                "social_security": ss,
                "medicare": medicare,
                "health_insurance": health,
                "401k": k401,
                "total_deductions": total_ded,
                "net_pay": net,
                # Running totals
                "ytd_gross": running_gross,
                "ytd_net": running_net,
            })

        return {
            "document_type": "ytd",
            "form_title": f"Year-to-Date Earnings Summary — {current_year}",
            "year": current_year,
            "through_month": month_names[current_month - 1],
            "employer": {
                "name": employee.employer_name,
                "ein": employee.employer_ein,
            },
            "employee": {
                "name": employee.full_name,
                "email": employee.email,
                "employee_id": employee.employee_id,
                "department": employee.department,
                "title": employee.title,
                "state": employee.state,
            },
            "monthly_breakdown": months_data,
            "totals": {
                "gross": running_gross,
                "federal_tax": running_fed,
                "state_tax": running_state,
                "social_security": running_ss,
                "medicare": running_medicare,
                "health_insurance": running_health,
                "401k": running_k401,
                "total_deductions": round(
                    running_fed + running_state + running_ss
                    + running_medicare + running_health + running_k401,
                    2,
                ),
                "net_pay": running_net,
            },
        }
