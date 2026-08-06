"""
scout/connectors/mock/netsuite.py — Mock NetSuite ERP connector.

NetSuite is the source of truth for:
  - Vendors (every company you pay money to)
  - Invoices (AP — what you owe; AR — what customers owe you)
  - Chart of Accounts (how money is categorised)
  - Purchase Orders

For Miragent's Margin Expansion Workers, NetSuite is critical:
  - Vendor Intelligence uses vendor spend, contract terms, renewal dates
  - Working Capital Worker uses AR aging, DSO, AP payment timing
  - Cost of Revenue Worker uses expense categorization by cost center

Sprint 17: Expanded to 40 vendors with realistic spend data (~$1.8M/yr total),
contract renewals spread over 18 months, and richer invoice set.
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
    Build deterministic mock NetSuite data seeded by tenant.
    Returns dict with keys: vendor, invoice.
    """
    rng = random.Random(seed)
    today = datetime(2026, 5, 12)

    def _date_str(d: datetime) -> str:
        return d.strftime("%Y-%m-%d")

    def _days_from_now(n: int) -> str:
        return _date_str(today + timedelta(days=n))

    def _days_ago(n: int) -> str:
        return _date_str(today - timedelta(days=n))

    # ── Vendor master list ────────────────────────────────────────────────────
    # (internal_id, entity_name, email, category, subcategory, annual_spend,
    #  payment_terms, renewal_days_from_now, is_managed)
    # renewal_days_from_now = None means no fixed renewal (e.g. month-to-month or usage)
    # Total spend target ~$1.8M/year
    vendor_templates = [
        # CRM
        ("V-001", "Salesforce Inc",        "billing@salesforce.com",   "Software", "CRM",           180_000, "Net-30",  210, True),
        ("V-002", "HubSpot Inc",           "billing@hubspot.com",      "Software", "CRM",            45_000, "Net-30",  380, True),
        # HRIS
        ("V-003", "Workday Inc",           "billing@workday.com",      "Software", "HRIS",           220_000, "Net-30",  290, True),
        ("V-004", "BambooHR LLC",          "billing@bamboohr.com",     "Software", "HRIS",            28_000, "Net-30",  420, False),
        # ERP / Finance
        ("V-005", "Oracle NetSuite",       "billing@netsuite.com",     "Software", "ERP",             95_000, "Net-45",  155, True),
        ("V-006", "Sage Intacct",          "billing@sage.com",         "Software", "ERP",             42_000, "Net-30",  480, False),
        # Analytics / BI
        ("V-007", "Tableau Software",      "billing@tableau.com",      "Software", "Analytics",       65_000, "Net-30",  320, True),
        ("V-008", "Looker (Google)",       "billing@looker.com",       "Software", "Analytics",       85_000, "Net-30",  190, True),
        ("V-009", "Snowflake Inc",         "billing@snowflake.com",    "Software", "Data Platform",  120_000, "Net-30",   None, True),  # usage-based
        # Productivity / Collaboration
        ("V-010", "Microsoft Corp",        "billing@microsoft.com",    "Software", "Productivity",    85_000, "Net-30",  365, True),
        ("V-011", "Slack Technologies",    "billing@slack.com",        "Software", "Collaboration",   38_000, "Annual",  270, True),
        ("V-012", "Zoom Video Comms",      "billing@zoom.us",          "Software", "Video Conf",      22_000, "Annual",  340, True),
        # Security
        ("V-013", "Okta Inc",              "billing@okta.com",         "Software", "Identity",        55_000, "Net-30",  410, True),
        ("V-014", "CrowdStrike Inc",       "billing@crowdstrike.com",  "Software", "Security",        78_000, "Net-30",   22, True),   # CRITICAL — renews in 22 days
        ("V-015", "Qualys Inc",            "billing@qualys.com",       "Software", "Security",        28_000, "Net-45",  495, False),
        # DevTools / Engineering
        ("V-016", "GitHub Inc",            "billing@github.com",       "Software", "DevTools",        18_000, "Annual",   90, True),
        ("V-017", "Atlassian Corp",        "billing@atlassian.com",    "Software", "DevTools",        24_000, "Annual",  180, True),
        ("V-018", "Datadog Inc",           "billing@datadoghq.com",    "Software", "Observability",   95_000, "Net-30",   None, True),  # usage-based
        # Marketing
        ("V-019", "Adobe Marketo",         "billing@adobe.com",        "Software", "Marketing Auto",  72_000, "Net-45",  260, True),
        ("V-020", "Outreach Inc",          "billing@outreach.io",      "Software", "Sales Engagement",48_000, "Net-30",  310, True),
        ("V-021", "ZoomInfo Tech",         "billing@zoominfo.com",     "Software", "Data/Intel",      60_000, "Net-30",   14, True),   # CRITICAL — renews in 14 days
        # Finance / AP
        ("V-022", "Expensify Inc",         "billing@expensify.com",    "Software", "Expense Mgmt",    12_000, "Net-30",  540, False),
        ("V-023", "Coupa Software",        "billing@coupa.com",        "Software", "Procurement",     45_000, "Net-45",  200, True),
        ("V-024", "Brex Inc",              "billing@brex.com",         "Software", "Corp Cards",       8_000, "Monthly",  None, False),  # monthly
        # HR / Benefits
        ("V-025", "Gusto Inc",             "billing@gusto.com",        "Software", "Payroll",         22_000, "Monthly",  None, False),  # monthly
        ("V-026", "Lattice Inc",           "billing@lattice.com",      "Software", "Performance",     18_000, "Net-30",  440, False),
        ("V-027", "Greenhouse Software",   "billing@greenhouse.io",    "Software", "ATS",             35_000, "Net-30",  350, True),
        # Customer Success
        ("V-028", "Gainsight Inc",         "billing@gainsight.com",    "Software", "CS Platform",     65_000, "Net-30",  280, True),
        ("V-029", "Zendesk Inc",           "billing@zendesk.com",      "Software", "Support",         42_000, "Net-30",  160, True),
        # Legal
        ("V-030", "DocuSign Inc",          "billing@docusign.com",     "Software", "eSign",           18_000, "Annual",   28, True),   # CRITICAL — renews in 28 days
        ("V-031", "Ironclad Inc",          "billing@ironcladapp.com",  "Software", "CLM",             28_000, "Net-30",  510, True),
        # Cloud Infrastructure
        ("V-032", "Amazon Web Services",   "aws-billing@amazon.com",   "Cloud Infrastructure", "IaaS", 480_000, "Monthly", None, True),  # usage-based — largest spend
        ("V-033", "Google Cloud Platform", "billing@google.com",       "Cloud Infrastructure", "IaaS",  85_000, "Monthly", None, False),
        # Professional Services
        ("V-034", "Deloitte LLP",          "billing@deloitte.com",     "Professional Services", "Advisory", 320_000, "Net-45", None, True),
        ("V-035", "Gartner Inc",           "billing@gartner.com",      "Research", "Analyst",         65_000, "Annual",  390, True),
        # Other SaaS
        ("V-036", "Notion Labs",           "billing@notion.so",        "Software", "Productivity",    12_000, "Annual",  470, False),
        ("V-037", "Figma Inc",             "billing@figma.com",        "Software", "Design",          24_000, "Annual",  230, True),
        ("V-038", "Gong.io Inc",           "billing@gong.io",          "Software", "Revenue Intel",   55_000, "Net-30",  175, True),
        ("V-039", "PagerDuty Inc",         "billing@pagerduty.com",    "Software", "Incident Mgmt",   22_000, "Net-30",  400, True),
        ("V-040", "Twilio Inc",            "billing@twilio.com",       "Software", "Communications",  35_000, "Monthly",  None, False),  # usage-based
    ]

    vendors = []
    for (vid, name, email, category, subcategory, annual_spend,
         payment_terms, renewal_days, is_managed) in vendor_templates:
        renewal_date = _days_from_now(renewal_days) if renewal_days is not None else None
        phone = f"1-{rng.randint(200,999)}-{rng.randint(200,999)}-{rng.randint(1000,9999)}"
        vendors.append({
            "internalId":         vid,
            "entityId":           name,
            "email":              email,
            "phone":              phone,
            "isActive":           True,
            "category":           category,
            "subcategory":        subcategory,
            "paymentTerms":       payment_terms,
            "annualSpend":        annual_spend,
            "contractRenewal":    renewal_date,
            "isManagedContract":  is_managed,
            "primaryContact":     rng.choice(["Account Manager", "Customer Success", "Enterprise Sales", "TAM", "Engagement Partner"]),
        })

    # ── Invoices (realistic AP invoice set) ───────────────────────────────────
    invoice_templates = [
        # Open invoices
        ("INV-1001", "V-001", -30, -0,   23_667, "Open",    "Salesforce Enterprise — Monthly"),
        ("INV-1002", "V-003", -30, -0,   18_333, "Open",    "Workday HCM — Monthly"),
        ("INV-1003", "V-011",  -7, 23,    3_167, "Open",    "Slack Pro — Monthly"),
        ("INV-1004", "V-028", -14, 16,    5_417, "Open",    "Gainsight Platform — Monthly"),
        ("INV-1005", "V-017", -20, 10,   24_000, "Open",    "Atlassian Jira/Confluence — Annual Renewal"),
        ("INV-1006", "V-029", -10, 20,    3_500, "Open",    "Zendesk Support — Monthly"),
        # Paid invoices
        ("INV-1007", "V-032", -35, -5,   41_200, "Paid",    "AWS Usage — Prior Month"),
        ("INV-1008", "V-001", -60, -30,  23_667, "Paid",    "Salesforce Enterprise — Prior Month"),
        ("INV-1009", "V-005", -90, -45,  95_000, "Paid",    "NetSuite Annual License"),
        ("INV-1010", "V-013", -60, -15,  55_000, "Paid",    "Okta Identity — Annual"),
        ("INV-1011", "V-007", -45, -15,  65_000, "Paid",    "Tableau — Annual Renewal"),
        ("INV-1012", "V-019", -30, -0,    6_000, "Paid",    "Marketo — Monthly"),
        ("INV-1013", "V-012", -45, -15,  22_000, "Paid",    "Zoom — Annual"),
        ("INV-1014", "V-016", -60, -30,  18_000, "Paid",    "GitHub Enterprise — Annual"),
        ("INV-1015", "V-033", -30, -0,    7_083, "Paid",    "GCP Usage — Monthly"),
        # Overdue invoices — critical for Working Capital Worker
        ("INV-1016", "V-034", -75, -30,  80_000, "Overdue", "Deloitte Advisory — Q4 Engagement"),
        ("INV-1017", "V-035", -95, -50,  65_000, "Overdue", "Gartner Research — Annual Access"),
        ("INV-1018", "V-023", -50, -5,   45_000, "Overdue", "Coupa Procurement Suite — Annual"),
        # Recent paid
        ("INV-1019", "V-014", -15, 15,   78_000, "Open",    "CrowdStrike — Annual Renewal"),
        ("INV-1020", "V-027", -20,  10,  35_000, "Open",    "Greenhouse ATS — Annual"),
    ]

    invoices = []
    for (inv_id, vendor_id, tran_offset, due_offset, amount, status, memo) in invoice_templates:
        tran_date = _days_ago(-tran_offset)  # negative offset = days ago
        due_date_val = today + timedelta(days=due_offset)
        invoices.append({
            "internalId": inv_id,
            "vendorId":   vendor_id,
            "tranDate":   tran_date,
            "dueDate":    _date_str(due_date_val),
            "amount":     amount,
            "status":     status,
            "memo":       memo,
        })

    return {"vendor": vendors, "invoice": invoices}


# Build the module-level fixture data (seeded with default tenant)
_ENTITY_DATA = _build_mock_data(seed=42)


class NetsuiteMockConnector(ConnectorBase):
    """Mock NetSuite ERP connector — the financial data source of truth."""

    CONNECTOR_ID = "netsuite"
    DISPLAY_NAME = "NetSuite ERP"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 2.0  # NetSuite's SuiteQL API has strict limits

    def _get_entity_data(self) -> dict[str, list[dict]]:
        """Return deterministic data seeded by tenant_id."""
        seed = hash(self.tenant_id) % (2**31)
        return _build_mock_data(seed=seed)

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        data = self._get_entity_data()
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="NetSuite Vendors",
                supports_incremental=True,
                estimated_record_count=len(data["vendor"]),
                fields=["internalId", "entityId", "email", "category", "subcategory",
                        "annualSpend", "contractRenewal", "isManagedContract", "paymentTerms"],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="AP Invoices",
                supports_incremental=True,
                estimated_record_count=len(data["invoice"]),
                fields=["internalId", "vendorId", "tranDate", "dueDate", "amount", "status"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        data = self._get_entity_data()
        if entity_type not in data:
            raise ValueError(f"NetSuite connector does not support entity type: {entity_type}")

        for raw in data[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["internalId"],
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=raw.get("entityId"),  # vendor name
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        data = self._get_entity_data()
        all_records = list(data.get(entity_type, []))
        changed = [r for r in all_records if random.random() < 0.10]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=raw["internalId"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=raw.get("entityId"),
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
            latency_ms=145.0,  # NetSuite is characteristically slow
        )
