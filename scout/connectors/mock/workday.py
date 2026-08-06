"""
scout/connectors/mock/workday.py — Mock Workday HCM connector.

Workday is the source of truth for:
  - Worker records (the canonical employee record)
  - Org structure (who reports to whom)
  - Job profiles, departments, cost centers
  - Compensation bands (when permitted)

In Miragent, Workday is the HIGHEST PRIORITY source of truth for
people data. If Workday says someone's department is "Engineering"
but Salesforce says "Product", Workday wins.

Sprint 17: Expanded to 80 workers with realistic hierarchy, salary bands,
employment types, and cost centers. Data is deterministic — seeded by tenant_id.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
import random

from scout.connectors.base import ConnectorBase
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ConnectorHealth,
    EntitySchema,
    ExtractionCursor,
    RawRecord,
)


def _build_mock_data(seed: int = 42) -> tuple[list[dict], list[dict]]:
    """
    Build deterministic mock Workday data seeded by tenant.
    Returns (workers, departments).
    """
    rng = random.Random(seed)

    # ── Department definitions ────────────────────────────────────────────────
    departments = [
        {"departmentId": "DEPT-100", "name": "Sales",            "costCenter": "CC-100", "parentDepartmentId": None},
        {"departmentId": "DEPT-200", "name": "Engineering",      "costCenter": "CC-200", "parentDepartmentId": None},
        {"departmentId": "DEPT-300", "name": "Finance",          "costCenter": "CC-300", "parentDepartmentId": None},
        {"departmentId": "DEPT-400", "name": "Marketing",        "costCenter": "CC-400", "parentDepartmentId": None},
        {"departmentId": "DEPT-500", "name": "Operations",       "costCenter": "CC-500", "parentDepartmentId": None},
        {"departmentId": "DEPT-600", "name": "HR",               "costCenter": "CC-600", "parentDepartmentId": None},
        {"departmentId": "DEPT-700", "name": "Customer Success", "costCenter": "CC-700", "parentDepartmentId": None},
        {"departmentId": "DEPT-800", "name": "Legal",            "costCenter": "CC-800", "parentDepartmentId": None},
        {"departmentId": "DEPT-101", "name": "Inside Sales",     "costCenter": "CC-101", "parentDepartmentId": "DEPT-100"},
        {"departmentId": "DEPT-102", "name": "Sales Engineering","costCenter": "CC-102", "parentDepartmentId": "DEPT-100"},
        {"departmentId": "DEPT-201", "name": "Platform Eng",     "costCenter": "CC-201", "parentDepartmentId": "DEPT-200"},
        {"departmentId": "DEPT-202", "name": "Data Engineering", "costCenter": "CC-202", "parentDepartmentId": "DEPT-200"},
        {"departmentId": "DEPT-301", "name": "FP&A",             "costCenter": "CC-301", "parentDepartmentId": "DEPT-300"},
        {"departmentId": "DEPT-401", "name": "Demand Gen",       "costCenter": "CC-401", "parentDepartmentId": "DEPT-400"},
        {"departmentId": "DEPT-701", "name": "CS Operations",    "costCenter": "CC-701", "parentDepartmentId": "DEPT-700"},
    ]

    dept_by_name = {d["name"]: d for d in departments}

    # ── Salary bands by level ─────────────────────────────────────────────────
    salary_bands = {
        "VP":        (220_000, 320_000),
        "Director":  (180_000, 260_000),
        "Manager":   (140_000, 200_000),
        "Senior":    (120_000, 160_000),
        "IC":        (90_000,  140_000),
    }

    def _salary(level: str) -> int:
        lo, hi = salary_bands[level]
        return rng.randint(lo // 1000, hi // 1000) * 1000

    def _start_date(years_ago_max: float = 6.0) -> str:
        days_ago = int(rng.uniform(30, years_ago_max * 365))
        d = datetime(2026, 5, 12) - timedelta(days=days_ago)
        return d.strftime("%Y-%m-%d")

    locations = ["New York", "San Francisco", "Chicago", "Austin", "Remote", "Boston", "Seattle", "Denver"]

    # ── Build worker list ─────────────────────────────────────────────────────
    # Format: (workerId, name, email, jobTitle, department, level, managerId, employmentType)
    # managerId filled in after VPs defined

    workers: list[dict] = []
    worker_idx = [1]  # mutable counter

    def _add(name: str, email: str, title: str, dept: str, level: str,
             manager_id: str | None, emp_type: str = "Regular",
             is_active: bool = True) -> str:
        wid = f"WD-{worker_idx[0]:04d}"
        worker_idx[0] += 1
        cost_center = dept_by_name.get(dept, {}).get("costCenter", "CC-999")
        emp_id = f"EMP-{wid[3:]}"

        # last_login_sfdc: 85% within last 30 days, 15% over 60 days ago
        if rng.random() < 0.85:
            login_days_ago = rng.randint(0, 30)
        else:
            login_days_ago = rng.randint(61, 365)
        last_login = (datetime(2026, 5, 12) - timedelta(days=login_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

        workers.append({
            "workerId":       wid,
            "name":           name,
            "email":          email,
            "employeeId":     emp_id,
            "jobTitle":       title,
            "department":     dept,
            "managerId":      manager_id,
            "location":       rng.choice(locations),
            "employmentType": emp_type,
            "startDate":      _start_date(),
            "costCenter":     cost_center,
            "isActive":       is_active,
            "annualSalary":   _salary(level),
            "lastLoginSfdc":  last_login,
        })
        return wid

    # ── C-Suite / CEO placeholder ─────────────────────────────────────────────
    ceo_id = "WD-0099"  # external, not in our dataset

    # ── VP Layer (4 VPs) ──────────────────────────────────────────────────────
    vp_sales       = _add("Sarah Chen",          "s.chen@acmecorp.com",          "VP of Sales",            "Sales",            "VP",       ceo_id)
    vp_eng         = _add("Raj Krishnamurthy",   "r.krishnamurthy@acmecorp.com", "VP of Engineering",      "Engineering",      "VP",       ceo_id)
    vp_mktg        = _add("Diana Okonkwo",       "d.okonkwo@acmecorp.com",       "VP of Marketing",        "Marketing",        "VP",       ceo_id)
    vp_ops         = _add("James O'Brien",        "j.obrien@acmecorp.com",        "VP of Operations",       "Operations",       "VP",       ceo_id)

    # ── Finance (CFO + team, 8 people) ───────────────────────────────────────
    cfo            = _add("Amanda Foster",        "a.foster@acmecorp.com",        "CFO",                    "Finance",          "VP",       ceo_id)
    dir_fpa        = _add("Lisa Nakamura",        "l.nakamura@acmecorp.com",      "Director of FP&A",       "FP&A",             "Director", cfo)
    sr_acct1       = _add("Thomas Brennan",       "t.brennan@acmecorp.com",       "Senior Accountant",      "Finance",          "Senior",   dir_fpa,  "Regular", False)  # inactive
    sr_acct2       = _add("Mei Lin",              "m.lin@acmecorp.com",           "Senior Accountant",      "Finance",          "Senior",   dir_fpa)
    fin_analyst1   = _add("Kofi Mensah",          "k.mensah@acmecorp.com",        "Financial Analyst",      "FP&A",             "IC",       dir_fpa)
    fin_analyst2   = _add("Shreya Nair",          "s.nair@acmecorp.com",          "Financial Analyst",      "FP&A",             "IC",       dir_fpa)
    controller     = _add("Patrick Sullivan",     "p.sullivan@acmecorp.com",      "Controller",             "Finance",          "Director", cfo)
    ap_spec        = _add("Fatima Al-Hassan",     "f.alhassan@acmecorp.com",      "AP Specialist",          "Finance",          "IC",       controller, "Regular", False)  # inactive

    # ── HR (6 people) ────────────────────────────────────────────────────────
    chro           = _add("Ingrid Sorensen",      "i.sorensen@acmecorp.com",      "CHRO",                   "HR",               "VP",       ceo_id)
    hr_mgr         = _add("Olivia Bennett",       "o.bennett@acmecorp.com",       "HR Manager",             "HR",               "Manager",  chro)
    recruiter1     = _add("Lucas Ferreira",       "l.ferreira@acmecorp.com",      "Senior Recruiter",       "HR",               "Senior",   hr_mgr)
    recruiter2     = _add("Amara Diallo",         "a.diallo@acmecorp.com",        "Recruiter",              "HR",               "IC",       hr_mgr)
    hrbp1          = _add("Yuki Tanaka",          "y.tanaka@acmecorp.com",        "HR Business Partner",    "HR",               "Senior",   hr_mgr)
    hrbp2          = _add("Noah Williams",        "n.williams@acmecorp.com",      "HR Business Partner",    "HR",               "IC",       hr_mgr,   "Regular", False)  # inactive

    # ── Legal (4 people) ─────────────────────────────────────────────────────
    gc             = _add("Margaret Thornton",    "m.thornton@acmecorp.com",      "General Counsel",        "Legal",            "VP",       ceo_id)
    sr_counsel     = _add("Arjun Sharma",         "a.sharma@acmecorp.com",        "Senior Counsel",         "Legal",            "Senior",   gc)
    paralegal1     = _add("Sofia Reyes",          "s.reyes@acmecorp.com",         "Paralegal",              "Legal",            "IC",       gc)
    paralegal2     = _add("Ben Goldstein",        "b.goldstein@acmecorp.com",     "Contract Specialist",    "Legal",            "IC",       gc,       "Contractor")

    # ── Sales (20 people under VP of Sales) ──────────────────────────────────
    dir_ae         = _add("Marcus Thompson",      "m.thompson@acmecorp.com",      "Director, Account Executives","Sales",        "Director", vp_sales)
    dir_sdr        = _add("Jennifer Walsh",       "j.walsh@acmecorp.com",         "Director, Sales Dev",    "Inside Sales",     "Director", vp_sales)
    mgr_se         = _add("David Kim",            "d.kim@acmecorp.com",           "Sales Engineering Manager","Sales Engineering","Manager", vp_sales)
    revops_mgr     = _add("Nina Chakraborty",     "n.chakraborty@acmecorp.com",   "RevOps Manager",         "Operations",       "Manager",  vp_ops)

    ae1            = _add("Priya Patel",          "p.patel@acmecorp.com",         "Account Executive",      "Sales",            "Senior",   dir_ae)
    ae2            = _add("Marcus Johnson",       "m.johnson@acmecorp.com",       "Account Executive",      "Sales",            "Senior",   dir_ae)
    ae3            = _add("Robert Torres",        "r.torres@acmecorp.com",        "Account Executive",      "Sales",            "IC",       dir_ae)
    ae4            = _add("Aisha Kamara",         "a.kamara@acmecorp.com",        "Account Executive",      "Sales",            "IC",       dir_ae)
    ae5            = _add("Liam O'Connor",         "l.oconnor@acmecorp.com",       "Senior Account Executive","Sales",          "Senior",   dir_ae)
    ae6            = _add("Zara Ahmed",           "z.ahmed@acmecorp.com",         "Account Executive",      "Sales",            "IC",       dir_ae,   "Regular", False)  # inactive

    sdr1           = _add("Tyler Brooks",         "t.brooks@acmecorp.com",        "Sales Development Rep",  "Inside Sales",     "IC",       dir_sdr)
    sdr2           = _add("Emma Johansson",       "e.johansson@acmecorp.com",     "Sales Development Rep",  "Inside Sales",     "IC",       dir_sdr)
    sdr3           = _add("Carlos Mendez",        "c.mendez@acmecorp.com",        "Senior SDR",             "Inside Sales",     "Senior",   dir_sdr)
    sdr4           = _add("Aaliyah Robinson",     "a.robinson@acmecorp.com",      "Sales Development Rep",  "Inside Sales",     "IC",       dir_sdr)
    sdr5           = _add("Felix Wagner",         "f.wagner@acmecorp.com",        "Sales Development Rep",  "Inside Sales",     "IC",       dir_sdr,  "Regular", False)  # inactive

    se1            = _add("Daniel Park",          "d.park@acmecorp.com",          "Sales Engineer",         "Sales Engineering","Senior",   mgr_se)
    se2            = _add("Isabelle Dubois",      "i.dubois@acmecorp.com",        "Sales Engineer",         "Sales Engineering","IC",       mgr_se)
    se3            = _add("Hiroshi Yamamoto",     "h.yamamoto@acmecorp.com",      "Solutions Architect",    "Sales Engineering","Senior",   mgr_se,   "Contractor")

    # ── Engineering (16 people) ───────────────────────────────────────────────
    dir_plat       = _add("Elena Vasquez",        "e.vasquez@acmecorp.com",       "Director, Platform Eng", "Platform Eng",     "Director", vp_eng)
    dir_data       = _add("Kwame Asante",         "k.asante@acmecorp.com",        "Director, Data Eng",     "Data Engineering", "Director", vp_eng)
    mgr_backend    = _add("James Liu",            "j.liu@acmecorp.com",           "Engineering Manager",    "Platform Eng",     "Manager",  dir_plat)
    mgr_frontend   = _add("Nadia Petrov",         "n.petrov@acmecorp.com",        "Engineering Manager",    "Platform Eng",     "Manager",  dir_plat)

    swe1           = _add("Aisha Mohammed",       "a.mohammed@acmecorp.com",      "Senior Software Engineer","Platform Eng",    "Senior",   mgr_backend)
    swe2           = _add("Ethan Clarke",         "e.clarke@acmecorp.com",        "Software Engineer",      "Platform Eng",     "IC",       mgr_backend)
    swe3           = _add("Layla Haddad",         "l.haddad@acmecorp.com",        "Software Engineer",      "Platform Eng",     "IC",       mgr_backend, "Contractor")
    swe4           = _add("Oscar Lindqvist",      "o.lindqvist@acmecorp.com",     "Senior Software Engineer","Platform Eng",    "Senior",   mgr_frontend)
    swe5           = _add("Mei Chen",             "m.chen@acmecorp.com",          "Software Engineer",      "Platform Eng",     "IC",       mgr_frontend)
    swe6           = _add("Raj Patel",            "r.patel@acmecorp.com",         "Staff Engineer",         "Platform Eng",     "Senior",   dir_plat)

    de1            = _add("Zoe Fischer",          "z.fischer@acmecorp.com",       "Senior Data Engineer",   "Data Engineering", "Senior",   dir_data)
    de2            = _add("Ahmed Hassan",         "a.hassan@acmecorp.com",        "Data Engineer",          "Data Engineering", "IC",       dir_data)
    de3            = _add("Priya Krishnan",       "p.krishnan@acmecorp.com",      "Analytics Engineer",     "Data Engineering", "IC",       dir_data,  "Contractor")
    de4            = _add("William Osei",         "w.osei@acmecorp.com",          "Data Engineer",          "Data Engineering", "IC",       dir_data,  "Regular", False)  # inactive
    ml_eng         = _add("Ling Zhou",            "l.zhou@acmecorp.com",          "ML Engineer",            "Data Engineering", "Senior",   dir_data)

    # ── Marketing (12 people) ─────────────────────────────────────────────────
    dir_demand     = _add("Chloe Dupont",         "c.dupont@acmecorp.com",        "Director, Demand Gen",   "Demand Gen",       "Director", vp_mktg)
    mgr_content    = _add("Samuel Okafor",        "s.okafor@acmecorp.com",        "Content Marketing Manager","Marketing",      "Manager",  vp_mktg)

    mktg1          = _add("Hannah Kim",           "h.kim@acmecorp.com",           "Senior Demand Gen Manager","Demand Gen",     "Senior",   dir_demand)
    mktg2          = _add("Leo Brandt",           "l.brandt@acmecorp.com",        "Marketing Analyst",      "Demand Gen",       "IC",       dir_demand)
    mktg3          = _add("Fatou Diagne",         "f.diagne@acmecorp.com",        "Marketing Analyst",      "Demand Gen",       "IC",       dir_demand, "Part-time")
    mktg4          = _add("Akira Suzuki",         "a.suzuki@acmecorp.com",        "Senior Content Writer",  "Marketing",        "Senior",   mgr_content)
    mktg5          = _add("Isabella Rossi",       "i.rossi@acmecorp.com",         "Content Writer",         "Marketing",        "IC",       mgr_content)
    mktg6          = _add("Jordan Lee",           "j.lee@acmecorp.com",           "Brand Designer",         "Marketing",        "IC",       mgr_content)
    mktg7          = _add("Maya Goldberg",        "m.goldberg@acmecorp.com",      "Field Marketing Manager","Marketing",        "Senior",   vp_mktg)
    mktg8          = _add("Ravi Anand",           "r.anand@acmecorp.com",         "Marketing Ops Specialist","Marketing",       "IC",       vp_mktg,   "Regular", False)  # inactive
    mktg9          = _add("Simone Laurent",       "s.laurent@acmecorp.com",       "Product Marketing Manager","Marketing",      "Manager",  vp_mktg)
    pmm2           = _add("Alex Tanaka",          "a.tanaka@acmecorp.com",        "Product Marketing Analyst","Marketing",      "IC",       mktg9,     "Contractor")

    # ── Operations (6 people) ─────────────────────────────────────────────────
    dir_ops        = _add("Brendan Murphy",       "b.murphy@acmecorp.com",        "Director of Operations", "Operations",       "Director", vp_ops)
    ops1           = _add("Grace Ndungu",         "g.ndungu@acmecorp.com",        "Business Operations Manager","Operations",   "Manager",  dir_ops)
    ops2           = _add("Victor Petrov",        "v.petrov@acmecorp.com",        "IT Manager",             "Operations",       "Manager",  dir_ops)
    ops3           = _add("Jasmine Brown",        "j.brown@acmecorp.com",         "IT Specialist",          "Operations",       "IC",       ops2,      "Regular", False)  # inactive
    ops4           = _add("Tom Huang",            "t.huang@acmecorp.com",         "IT Specialist",          "Operations",       "IC",       ops2)
    ops5           = _add("Celine Beaumont",      "c.beaumont@acmecorp.com",      "Business Analyst",       "Operations",       "Senior",   ops1)

    # ── Customer Success (6 people) ───────────────────────────────────────────
    dir_cs         = _add("Maria Santos",         "m.santos@acmecorp.com",        "Director, Customer Success","Customer Success","Director", vp_ops)
    csm1           = _add("Kevin O'Reilly",        "k.oreilly@acmecorp.com",       "Senior CSM",             "Customer Success", "Senior",   dir_cs)
    csm2           = _add("Amelia Grant",         "a.grant@acmecorp.com",         "Customer Success Manager","CS Operations",   "Manager",  dir_cs)
    csm3           = _add("Sanjay Puri",          "s.puri@acmecorp.com",          "CSM",                    "Customer Success", "IC",       dir_cs)
    csm4           = _add("Lily Zhang",           "l.zhang@acmecorp.com",         "CSM",                    "Customer Success", "IC",       csm2)
    csm5           = _add("Marcus Webb",          "m.webb@acmecorp.com",          "Onboarding Specialist",  "CS Operations",    "IC",       csm2,      "Part-time")

    # ── Finalize department manager references ────────────────────────────────
    dept_managers = {
        "Sales":            vp_sales,
        "Engineering":      vp_eng,
        "Finance":          cfo,
        "Marketing":        vp_mktg,
        "Operations":       vp_ops,
        "HR":               chro,
        "Customer Success": dir_cs,
        "Legal":            gc,
        "Inside Sales":     dir_sdr,
        "Sales Engineering": mgr_se,
        "Platform Eng":     dir_plat,
        "Data Engineering": dir_data,
        "FP&A":             dir_fpa,
        "Demand Gen":       dir_demand,
        "CS Operations":    csm2,
    }

    # Compute headcount per department
    dept_headcounts: dict[str, int] = {}
    for w in workers:
        dept_headcounts[w["department"]] = dept_headcounts.get(w["department"], 0) + 1

    for d in departments:
        name = d["name"]
        d["managerId"] = dept_managers.get(name, ceo_id)
        d["headcount"] = dept_headcounts.get(name, 0)

    return workers, departments


# Build the module-level fixture data (seeded with default tenant)
_MOCK_WORKERS, _MOCK_DEPARTMENTS = _build_mock_data(seed=42)

_ENTITY_DATA: dict[str, list[dict]] = {
    "worker": _MOCK_WORKERS,
    "department": _MOCK_DEPARTMENTS,
}


class WorkdayMockConnector(ConnectorBase):
    """Mock Workday HCM connector — the people data source of truth."""

    CONNECTOR_ID = "workday"
    DISPLAY_NAME = "Workday HCM"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 3.0  # Workday rate limits are strict — real limit ~180/min

    def _get_entity_data(self) -> dict[str, list[dict]]:
        """Return deterministic data seeded by tenant_id."""
        seed = hash(self.tenant_id) % (2**31)
        workers, departments = _build_mock_data(seed=seed)
        return {"worker": workers, "department": departments}

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        data = self._get_entity_data()
        return [
            EntitySchema(
                entity_type="worker",
                display_name="Workday Workers",
                supports_incremental=True,
                estimated_record_count=len(data["worker"]),
                fields=["workerId", "name", "email", "employeeId", "jobTitle", "department",
                        "managerId", "employmentType", "isActive", "annualSalary", "costCenter"],
            ),
            EntitySchema(
                entity_type="department",
                display_name="Workday Departments",
                supports_incremental=False,
                estimated_record_count=len(data["department"]),
                fields=["departmentId", "name", "managerId", "costCenter", "parentDepartmentId"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        data = self._get_entity_data()
        if entity_type not in data:
            raise ValueError(f"Workday connector does not support entity type: {entity_type}")

        for raw in data[entity_type]:
            source_id = raw.get("workerId") or raw.get("departmentId", "")
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=source_id,
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("email"),
                name_hint=raw.get("name"),
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        data = self._get_entity_data()
        all_records = list(data.get(entity_type, []))
        changed = [r for r in all_records if random.random() < 0.15]  # 15% change rate

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                source_id = raw.get("workerId") or raw.get("departmentId", "")
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("email"),
                    name_hint=raw.get("name"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"last_modified_date": datetime.utcnow().isoformat()},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=38.2,  # Workday is slower than SFDC
        )
