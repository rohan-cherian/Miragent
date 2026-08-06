"""
scout/connectors/mock/salesforce.py — Mock Salesforce CRM connector.

Returns realistic fake data that mirrors the real Salesforce REST API shape.
Used on your laptop (USE_MOCK_CONNECTORS=true) and in CI tests.

Real Salesforce data looks like this — same field names, same structure.
When we build the real SalesforceConnector, the payload shapes are identical.
Only authenticate() and the HTTP calls change.

Salesforce entities Scout cares about:
  - User: every person with a Salesforce login (reps, managers, ops)
  - Account: companies in your CRM (customers, prospects, partners)
  - Opportunity: deals (open, won, lost)

Sprint 17: Expanded to 80 users, 50 accounts, 120 opportunities.
Data is deterministic — seeded by tenant_id.
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


def _build_mock_data(seed: int = 42) -> dict[str, list[dict]]:
    """
    Build deterministic mock Salesforce data seeded by tenant.
    Returns dict with keys: user, account, opportunity.
    """
    rng = random.Random(seed)

    today = datetime(2026, 5, 12)

    def _sfdc_id(prefix: str, n: int) -> str:
        return f"{prefix}{n:04d}"

    def _date_str(d: datetime) -> str:
        return d.strftime("%Y-%m-%d")

    def _dt_str(d: datetime) -> str:
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _days_ago(n: int) -> datetime:
        return today - timedelta(days=n)

    def _days_from_now(n: int) -> datetime:
        return today + timedelta(days=n)

    # ── Users (80 people) ────────────────────────────────────────────────────
    # People with SFDC logins — Sales, Marketing, Ops, CS, Finance
    user_data = [
        # Sales — VPs, Directors, AEs, SDRs, SEs
        ("Sarah Chen",         "s.chen@acmecorp.com",          "VP of Sales",                  "Sales",          True,  "00E0001"),
        ("Marcus Thompson",    "m.thompson@acmecorp.com",      "Director, Account Executives", "Sales",          True,  "00E0002"),
        ("Jennifer Walsh",     "j.walsh@acmecorp.com",         "Director, Sales Dev",          "Sales",          True,  "00E0002"),
        ("David Kim",          "d.kim@acmecorp.com",           "Sales Engineering Manager",    "Sales",          True,  "00E0003"),
        ("Priya Patel",        "p.patel@acmecorp.com",         "Senior Account Executive",     "Sales",          True,  "00E0004"),
        ("Marcus Johnson",     "m.johnson@acmecorp.com",       "Senior Account Executive",     "Sales",          True,  "00E0004"),
        ("Robert Torres",      "r.torres@acmecorp.com",        "Account Executive",            "Sales",          True,  "00E0004"),
        ("Aisha Kamara",       "a.kamara@acmecorp.com",        "Account Executive",            "Sales",          True,  "00E0004"),
        ("Liam O'Connor",      "l.oconnor@acmecorp.com",       "Senior Account Executive",     "Sales",          True,  "00E0004"),
        ("Zara Ahmed",         "z.ahmed@acmecorp.com",         "Account Executive",            "Sales",          False, "00E0004"),
        ("Tyler Brooks",       "t.brooks@acmecorp.com",        "Sales Development Rep",        "Sales",          True,  "00E0005"),
        ("Emma Johansson",     "e.johansson@acmecorp.com",     "Sales Development Rep",        "Sales",          True,  "00E0005"),
        ("Carlos Mendez",      "c.mendez@acmecorp.com",        "Senior SDR",                   "Sales",          True,  "00E0005"),
        ("Aaliyah Robinson",   "a.robinson@acmecorp.com",      "Sales Development Rep",        "Sales",          True,  "00E0005"),
        ("Felix Wagner",       "f.wagner@acmecorp.com",        "Sales Development Rep",        "Sales",          False, "00E0005"),
        ("Daniel Park",        "d.park@acmecorp.com",          "Sales Engineer",               "Sales",          True,  "00E0006"),
        ("Isabelle Dubois",    "i.dubois@acmecorp.com",        "Sales Engineer",               "Sales",          True,  "00E0006"),
        ("Hiroshi Yamamoto",   "h.yamamoto@acmecorp.com",      "Solutions Architect",          "Sales",          True,  "00E0006"),
        ("Nina Chakraborty",   "n.chakraborty@acmecorp.com",   "RevOps Manager",               "Operations",     True,  "00E0007"),
        # Marketing
        ("Diana Okonkwo",      "d.okonkwo@acmecorp.com",       "VP of Marketing",              "Marketing",      True,  "00E0008"),
        ("Chloe Dupont",       "c.dupont@acmecorp.com",        "Director, Demand Gen",         "Marketing",      True,  "00E0009"),
        ("Samuel Okafor",      "s.okafor@acmecorp.com",        "Content Marketing Manager",    "Marketing",      True,  "00E0009"),
        ("Hannah Kim",         "h.kim@acmecorp.com",           "Senior Demand Gen Manager",    "Marketing",      True,  "00E0010"),
        ("Leo Brandt",         "l.brandt@acmecorp.com",        "Marketing Analyst",            "Marketing",      True,  "00E0010"),
        ("Fatou Diagne",       "f.diagne@acmecorp.com",        "Marketing Analyst",            "Marketing",      True,  "00E0010"),
        ("Akira Suzuki",       "a.suzuki@acmecorp.com",        "Senior Content Writer",        "Marketing",      True,  "00E0011"),
        ("Isabella Rossi",     "i.rossi@acmecorp.com",         "Content Writer",               "Marketing",      True,  "00E0011"),
        ("Jordan Lee",         "j.lee@acmecorp.com",           "Brand Designer",               "Marketing",      True,  "00E0011"),
        ("Maya Goldberg",      "m.goldberg@acmecorp.com",      "Field Marketing Manager",      "Marketing",      True,  "00E0011"),
        ("Ravi Anand",         "r.anand@acmecorp.com",         "Marketing Ops Specialist",     "Marketing",      False, "00E0011"),
        ("Simone Laurent",     "s.laurent@acmecorp.com",       "Product Marketing Manager",    "Marketing",      True,  "00E0011"),
        ("Alex Tanaka",        "a.tanaka@acmecorp.com",        "Product Marketing Analyst",    "Marketing",      True,  "00E0011"),
        # Customer Success
        ("Maria Santos",       "m.santos@acmecorp.com",        "Director, Customer Success",   "Customer Success",True, "00E0012"),
        ("Kevin O'Reilly",     "k.oreilly@acmecorp.com",       "Senior CSM",                   "Customer Success",True, "00E0013"),
        ("Amelia Grant",       "a.grant@acmecorp.com",         "Customer Success Manager",     "Customer Success",True, "00E0013"),
        ("Sanjay Puri",        "s.puri@acmecorp.com",          "CSM",                          "Customer Success",True, "00E0013"),
        ("Lily Zhang",         "l.zhang@acmecorp.com",         "CSM",                          "Customer Success",True, "00E0013"),
        ("Marcus Webb",        "m.webb@acmecorp.com",          "Onboarding Specialist",        "Customer Success",True, "00E0013"),
        # Finance (some have SFDC for billing/reporting)
        ("Amanda Foster",      "a.foster@acmecorp.com",        "CFO",                          "Finance",        True,  "00E0014"),
        ("Lisa Nakamura",      "l.nakamura@acmecorp.com",      "Director of FP&A",             "Finance",        True,  "00E0014"),
        ("Thomas Brennan",     "t.brennan@acmecorp.com",       "Senior Accountant",            "Finance",        False, "00E0014"),
        ("Mei Lin",            "m.lin@acmecorp.com",           "Senior Accountant",            "Finance",        True,  "00E0014"),
        # Engineering (some managers)
        ("Raj Krishnamurthy",  "r.krishnamurthy@acmecorp.com", "VP of Engineering",            "Engineering",    True,  "00E0015"),
        ("Elena Vasquez",      "e.vasquez@acmecorp.com",       "Director, Platform Eng",       "Engineering",    True,  "00E0015"),
        ("Kwame Asante",       "k.asante@acmecorp.com",        "Director, Data Eng",           "Engineering",    True,  "00E0015"),
        # Operations
        ("James O'Brien",      "j.obrien@acmecorp.com",        "VP of Operations",             "Operations",     True,  "00E0016"),
        ("Brendan Murphy",     "b.murphy@acmecorp.com",        "Director of Operations",       "Operations",     True,  "00E0016"),
        # HR
        ("Ingrid Sorensen",    "i.sorensen@acmecorp.com",      "CHRO",                         "HR",             True,  "00E0017"),
        ("Olivia Bennett",     "o.bennett@acmecorp.com",       "HR Manager",                   "HR",             True,  "00E0017"),
        ("Lucas Ferreira",     "l.ferreira@acmecorp.com",      "Senior Recruiter",             "HR",             True,  "00E0017"),
        # Legal
        ("Margaret Thornton",  "m.thornton@acmecorp.com",      "General Counsel",              "Legal",          True,  "00E0018"),
        ("Arjun Sharma",       "a.sharma@acmecorp.com",        "Senior Counsel",               "Legal",          True,  "00E0018"),
    ]

    # Build SFDC Users
    users = []
    # 15% last login > 60 days ago, 85% within 30 days
    for i, (name, email, title, dept, is_active, role_id) in enumerate(user_data, start=1):
        uid = _sfdc_id("005Dn0000", i)
        if rng.random() < 0.85:
            login_days = rng.randint(0, 30)
        else:
            login_days = rng.randint(61, 365)
        last_login = _dt_str(_days_ago(login_days))
        created_days = rng.randint(180, 6 * 365)
        created = _dt_str(_days_ago(created_days))
        users.append({
            "Id": uid,
            "Name": name,
            "Email": email,
            "Title": title,
            "Department": dept,
            "IsActive": is_active,
            "LastLoginDate": last_login,
            "CreatedDate": created,
            "UserRoleId": role_id,
        })

    # ── Accounts (50 accounts) ────────────────────────────────────────────────
    account_templates = [
        # Customers (30)
        ("Pinnacle Partners",        "Financial Services",   45_000_000,  320,  "Customer",  750_000),
        ("TechFlow Systems",         "Technology",          120_000_000,  850,  "Customer", 1_200_000),
        ("Meridian Healthcare",      "Healthcare",          280_000_000, 2100,  "Customer",  480_000),
        ("Apex Manufacturing",       "Manufacturing",        88_000_000,  640,  "Customer",  320_000),
        ("Sterling Financial",       "Financial Services",  210_000_000, 1400,  "Customer",  850_000),
        ("CloudFirst Retail",        "Retail",               32_000_000,  210,  "Customer",  180_000),
        ("BioLogic Labs",            "Healthcare",           55_000_000,  380,  "Customer",  240_000),
        ("DataCore Analytics",       "Technology",           78_000_000,  520,  "Customer",  560_000),
        ("Greenleaf Energy",         "Manufacturing",        95_000_000,  710,  "Customer",  390_000),
        ("Nexus Capital Group",      "Financial Services",  340_000_000, 2200,  "Customer", 1_800_000),
        ("SwiftShip Logistics",      "Manufacturing",        42_000_000,  290,  "Customer",  160_000),
        ("PrimeCare Medical",        "Healthcare",          175_000_000, 1200,  "Customer",  720_000),
        ("Horizon SaaS",             "Technology",           28_000_000,  180,  "Customer",  220_000),
        ("Atlantic Insurance",       "Financial Services",  130_000_000,  880,  "Customer",  640_000),
        ("Pulse Commerce",           "Retail",               67_000_000,  450,  "Customer",  290_000),
        ("NorthStar Consulting",     "Technology",           15_000_000,  120,  "Customer",  150_000),
        ("Cascade Manufacturing",    "Manufacturing",       155_000_000, 1050,  "Customer",  520_000),
        ("Vivid Media Group",        "Retail",               38_000_000,  260,  "Customer",  210_000),
        ("Summit Health Systems",    "Healthcare",          420_000_000, 3100,  "Customer", 2_000_000),
        ("TrueNorth Fintech",        "Financial Services",   22_000_000,  155,  "Customer",  190_000),
        ("Evergreen Industries",     "Manufacturing",        72_000_000,  490,  "Customer",  280_000),
        ("BlueSky Technologies",     "Technology",           45_000_000,  310,  "Customer",  350_000),
        ("Mosaic Retail Partners",   "Retail",               58_000_000,  400,  "Customer",  230_000),
        ("Zenith Pharma",            "Healthcare",          195_000_000, 1350,  "Customer",  880_000),
        ("Fortitude Capital",        "Financial Services",  280_000_000, 1900,  "Customer", 1_400_000),
        ("Pioneer Software",         "Technology",           35_000_000,  240,  "Customer",  260_000),
        ("Redwood Operations",       "Manufacturing",       110_000_000,  750,  "Customer",  420_000),
        ("Bright Path Education",    "Retail",               18_000_000,  140,  "Customer",   90_000),
        ("Iron Gate Security",       "Technology",           62_000_000,  420,  "Customer",  340_000),
        ("VitalCare Solutions",      "Healthcare",           88_000_000,  600,  "Customer",  460_000),
        # Prospects (15)
        ("Vertex Logistics",         "Manufacturing",        67_000_000,  430,  "Prospect",  None),
        ("Cascade Retail Group",     "Retail",               95_000_000,  670,  "Prospect",  None),
        ("Harbor Financial",         "Financial Services",  160_000_000, 1100,  "Prospect",  None),
        ("MedTech Innovations",      "Healthcare",           48_000_000,  340,  "Prospect",  None),
        ("Quantum Computing Co",     "Technology",           32_000_000,  220,  "Prospect",  None),
        ("Pacific Rim Retail",       "Retail",               75_000_000,  510,  "Prospect",  None),
        ("Granite Insurance",        "Financial Services",  220_000_000, 1600,  "Prospect",  None),
        ("Alpine Manufacturing",     "Manufacturing",       135_000_000,  920,  "Prospect",  None),
        ("NextWave Health",          "Healthcare",           62_000_000,  430,  "Prospect",  None),
        ("Stellar SaaS",             "Technology",           18_000_000,  130,  "Prospect",  None),
        ("Midwest Distribution",     "Manufacturing",        55_000_000,  380,  "Prospect",  None),
        ("Golden Gate Investments",  "Financial Services",  390_000_000, 2700,  "Prospect",  None),
        ("Emerald Retail Chain",     "Retail",               42_000_000,  290,  "Prospect",  None),
        ("Clarity Health Network",   "Healthcare",          115_000_000,  800,  "Prospect",  None),
        ("Axiom Tech Group",         "Technology",           85_000_000,  580,  "Prospect",  None),
        # Partners (5)
        ("Accenture LLP",            "Technology",        5_000_000_000, 50000, "Partner",   None),
        ("Deloitte Digital",         "Technology",        3_000_000_000, 40000, "Partner",   None),
        ("SalesForce Partners Inc",  "Technology",           50_000_000,  350,  "Partner",   None),
        ("TechStar Consulting",      "Technology",           12_000_000,   90,  "Partner",   None),
        ("CloudEdge Solutions",      "Technology",            8_000_000,   60,  "Partner",   None),
    ]

    # Sales rep user IDs (AEs who own accounts)
    ae_users = [u for u in users if "Account Executive" in u["Title"] and u["IsActive"]]
    csm_users = [u for u in users if "CSM" in u["Title"] and u["IsActive"]]
    all_sales = ae_users + csm_users

    industries = ["SaaS", "Manufacturing", "Healthcare", "Financial Services", "Retail", "Technology"]

    accounts = []
    for i, (name, industry, revenue, employees, acct_type, arr) in enumerate(account_templates, start=1):
        aid = _sfdc_id("001Dn0000", i)
        owner = rng.choice(all_sales) if all_sales else users[0]
        # ICP score correlated with revenue and industry
        base_icp = min(100, int(revenue / 5_000_000))
        icp_score = min(100, max(10, base_icp + rng.randint(-15, 15)))
        # Health score: 10% of customers below 40
        if acct_type == "Customer":
            if rng.random() < 0.10:
                health_score = rng.randint(15, 39)
            else:
                health_score = rng.randint(50, 98)
        else:
            health_score = None
        created_days = rng.randint(90, 5 * 365)
        accounts.append({
            "Id": aid,
            "Name": name,
            "Industry": industry,
            "AnnualRevenue": revenue,
            "NumberOfEmployees": employees,
            "OwnerId": owner["Id"],
            "Type": acct_type,
            "CreatedDate": _dt_str(_days_ago(created_days)),
            "ARR__c": arr,
            "ICP_Score__c": icp_score,
            "Health_Score__c": health_score,
        })

    # ── Opportunities (120 opportunities) ────────────────────────────────────
    # Distribution: 40 won, 30 lost, 50 open
    # Open stages: Prospecting 20%, Qualification 20%, Discovery 15%, Proposal 20%,
    #              Negotiation 15%, Contract 10%
    open_stages = [
        ("Prospecting",           10, 0.20),
        ("Qualification",         20, 0.20),
        ("Discovery",             30, 0.15),
        ("Proposal/Price Quote",  60, 0.20),
        ("Negotiation/Review",    75, 0.15),
        ("Contract Review",       90, 0.10),
    ]

    # Customer accounts for won/lost; any account for open
    customer_accounts = [a for a in accounts if a["Type"] == "Customer"]
    prospect_accounts = [a for a in accounts if a["Type"] == "Prospect"]
    all_deal_accounts = customer_accounts + prospect_accounts

    # Sales reps for opportunity owners
    sales_reps = [u for u in users if u["Department"] == "Sales" and u["IsActive"]
                  and any(t in u["Title"] for t in ["Account Executive", "SDR", "Senior SDR"])]
    if not sales_reps:
        sales_reps = [users[0]]

    def _opp_amount(account: dict) -> int:
        """Amount correlated with account size."""
        base = min(500_000, max(25_000, int(account["AnnualRevenue"] / 200)))
        jitter = rng.randint(-10_000, 50_000)
        return max(25_000, round((base + jitter) / 5_000) * 5_000)

    opportunities = []

    # Won deals (40)
    for i in range(1, 41):
        oid = _sfdc_id("006Dn0000", i)
        acct = rng.choice(customer_accounts) if customer_accounts else rng.choice(all_deal_accounts)
        owner = rng.choice(sales_reps)
        close_days_ago = rng.randint(30, 730)
        created_days_ago = close_days_ago + rng.randint(30, 180)
        amount = _opp_amount(acct)
        opportunities.append({
            "Id": oid,
            "Name": f"{acct['Name']} — {rng.choice(['Platform License', 'Enterprise Expansion', 'Renewal + Upsell', 'New Logo', 'Multi-Year Deal'])}",
            "StageName": "Closed Won",
            "Amount": amount,
            "CloseDate": _date_str(_days_ago(close_days_ago)),
            "AccountId": acct["Id"],
            "OwnerId": owner["Id"],
            "Probability": 100,
            "CreatedDate": _dt_str(_days_ago(created_days_ago)),
            "IsClosed": True,
            "IsWon": True,
            "Days_In_Stage__c": 0,
        })

    # Lost deals (30)
    for i in range(41, 71):
        oid = _sfdc_id("006Dn0000", i)
        acct = rng.choice(all_deal_accounts)
        owner = rng.choice(sales_reps)
        close_days_ago = rng.randint(14, 730)
        created_days_ago = close_days_ago + rng.randint(30, 150)
        amount = _opp_amount(acct)
        opportunities.append({
            "Id": oid,
            "Name": f"{acct['Name']} — {rng.choice(['Pilot', 'New Logo', 'Expansion', 'Platform Evaluation'])}",
            "StageName": "Closed Lost",
            "Amount": amount,
            "CloseDate": _date_str(_days_ago(close_days_ago)),
            "AccountId": acct["Id"],
            "OwnerId": owner["Id"],
            "Probability": 0,
            "CreatedDate": _dt_str(_days_ago(created_days_ago)),
            "IsClosed": True,
            "IsWon": False,
            "Days_In_Stage__c": 0,
        })

    # Open deals (50) — spread across stages
    stage_counts = {
        "Prospecting":           10,
        "Qualification":         10,
        "Discovery":              8,
        "Proposal/Price Quote":  10,
        "Negotiation/Review":     7,
        "Contract Review":        5,
    }
    stage_probs = {
        "Prospecting":           10,
        "Qualification":         20,
        "Discovery":             30,
        "Proposal/Price Quote":  60,
        "Negotiation/Review":    75,
        "Contract Review":       90,
    }

    opp_idx = 71
    for stage, count in stage_counts.items():
        for _ in range(count):
            oid = _sfdc_id("006Dn0000", opp_idx)
            opp_idx += 1
            acct = rng.choice(all_deal_accounts)
            owner = rng.choice(sales_reps)
            close_days_from_now = rng.randint(7, 180)
            created_days_ago = rng.randint(90, 540)
            amount = _opp_amount(acct)
            # 15% of open deals are stalled (>60 days in stage)
            if rng.random() < 0.15:
                days_in_stage = rng.randint(61, 150)
            else:
                days_in_stage = rng.randint(1, 45)
            opportunities.append({
                "Id": oid,
                "Name": f"{acct['Name']} — {rng.choice(['Platform License', 'New Logo', 'Expansion', 'Q2 Evaluation', 'Enterprise Deal', 'Strategic Pilot'])}",
                "StageName": stage,
                "Amount": amount,
                "CloseDate": _date_str(_days_from_now(close_days_from_now)),
                "AccountId": acct["Id"],
                "OwnerId": owner["Id"],
                "Probability": stage_probs[stage],
                "CreatedDate": _dt_str(_days_ago(created_days_ago)),
                "IsClosed": False,
                "IsWon": False,
                "Days_In_Stage__c": days_in_stage,
            })

    return {
        "user": users,
        "account": accounts,
        "opportunity": opportunities,
    }


# Build the module-level fixture data (seeded with default tenant)
_ENTITY_DATA = _build_mock_data(seed=42)


class SalesforceMockConnector(ConnectorBase):
    """
    Mock Salesforce connector — returns fixture data, no real API calls.

    Implements the full ConnectorBase interface so the orchestrator
    can't tell the difference between this and the real thing.
    """

    CONNECTOR_ID = "salesforce"
    DISPLAY_NAME = "Salesforce CRM"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 10.0  # Salesforce limit is ~100/min per user

    def _get_entity_data(self) -> dict[str, list[dict]]:
        """Return deterministic data seeded by tenant_id."""
        seed = hash(self.tenant_id) % (2**31)
        return _build_mock_data(seed=seed)

    def authenticate(self) -> bool:
        """Mock auth always succeeds — no real OAuth needed on your laptop."""
        return True

    def discover_schema(self) -> list[EntitySchema]:
        """Return the entity types this connector can extract."""
        data = self._get_entity_data()
        return [
            EntitySchema(
                entity_type="user",
                display_name="Salesforce Users",
                supports_incremental=True,
                estimated_record_count=len(data["user"]),
                fields=["Id", "Name", "Email", "Title", "Department", "IsActive", "LastLoginDate"],
            ),
            EntitySchema(
                entity_type="account",
                display_name="Salesforce Accounts",
                supports_incremental=True,
                estimated_record_count=len(data["account"]),
                fields=["Id", "Name", "Industry", "AnnualRevenue", "NumberOfEmployees", "Type",
                        "ARR__c", "ICP_Score__c", "Health_Score__c"],
            ),
            EntitySchema(
                entity_type="opportunity",
                display_name="Opportunities",
                supports_incremental=True,
                estimated_record_count=len(data["opportunity"]),
                fields=["Id", "Name", "StageName", "Amount", "CloseDate", "Probability",
                        "Days_In_Stage__c"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Yield every record of the given entity type.
        In the real connector, this calls the Salesforce SOQL query API.
        Here, it reads from our fixture data.
        """
        data = self._get_entity_data()
        if entity_type not in data:
            raise ValueError(f"Salesforce connector does not support entity type: {entity_type}")

        for raw in data[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["Id"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("Email"),
                name_hint=raw.get("Name"),
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Return records modified since cursor.last_extracted_at.
        In the real connector, this uses SOQL: WHERE LastModifiedDate > :timestamp
        In the mock, we simulate this by returning a random subset.
        """
        data = self._get_entity_data()
        all_records = list(data.get(entity_type, []))

        # Simulate: ~30% of records changed since last run
        changed = [r for r in all_records if random.random() < 0.3]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=raw["Id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("Email"),
                    name_hint=raw.get("Name"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"soql_offset": len(all_records)},
        )

        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        """Mock health check — always healthy, instant response."""
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=12.4,  # realistic SFDC latency
        )
