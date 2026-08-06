"""
scout/connectors/mock/zoho.py — Mock Zoho CRM connector.

Zoho CRM for contacts and accounts.
Entity types: contact, account
"""

from collections.abc import Iterator
from datetime import datetime
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

_MOCK_CONTACTS = [
    {"id": "zh-ct001", "Full_Name": "Dmitri Volkov",       "Email": "d.volkov@arrowhead-ventures.com",    "Title": "Managing Director",        "Department": "Investment Management", "Account_Name": "Arrowhead Ventures",   "Lead_Status": "Qualified"},
    {"id": "zh-ct002", "Full_Name": "Priyanka Mehta",      "Email": "p.mehta@arrowhead-ventures.com",     "Title": "Associate Director",       "Department": "Investment Management", "Account_Name": "Arrowhead Ventures",   "Lead_Status": "Contacted"},
    {"id": "zh-ct003", "Full_Name": "Lawrence Fitzpatrick","Email": "l.fitzpatrick@harbor-insurance.com",  "Title": "Chief Underwriting Officer","Department": "Underwriting",          "Account_Name": "Harbor Insurance Group","Lead_Status": "Qualified"},
    {"id": "zh-ct004", "Full_Name": "Clarissa Boudreaux",  "Email": "c.boudreaux@harbor-insurance.com",   "Title": "VP of Claims",             "Department": "Claims",                "Account_Name": "Harbor Insurance Group","Lead_Status": "Contacted"},
    {"id": "zh-ct005", "Full_Name": "Oskar Bergmann",      "Email": "o.bergmann@nexus-pharma.com",         "Title": "Chief Commercial Officer", "Department": "Commercial",            "Account_Name": "Nexus Pharma",         "Lead_Status": "Qualified"},
    {"id": "zh-ct006", "Full_Name": "Tamara Mitchell",     "Email": "t.mitchell@nexus-pharma.com",         "Title": "Head of Business Dev",     "Department": "Business Development",  "Account_Name": "Nexus Pharma",         "Lead_Status": "Not Contacted"},
    {"id": "zh-ct007", "Full_Name": "Ivan Petrov",         "Email": "i.petrov@sagepoint-consulting.com",   "Title": "Senior Partner",           "Department": "Consulting",            "Account_Name": "Sagepoint Consulting", "Lead_Status": "Lost"},
    {"id": "zh-ct008", "Full_Name": "Helena Rosario",      "Email": "h.rosario@vantage-data.com",          "Title": "Chief Data Officer",       "Department": "Data & Analytics",      "Account_Name": "Vantage Data Corp",    "Lead_Status": "Qualified"},
]

_MOCK_ACCOUNTS = [
    {"id": "zh-ac001", "Account_Name": "Arrowhead Ventures",     "Industry": "Private Equity",     "Annual_Revenue": 420000000.0, "Employees": 65,   "Owner": {"id": "zh-usr01"}},
    {"id": "zh-ac002", "Account_Name": "Harbor Insurance Group", "Industry": "Insurance",          "Annual_Revenue": 195000000.0, "Employees": 780,  "Owner": {"id": "zh-usr02"}},
    {"id": "zh-ac003", "Account_Name": "Nexus Pharma",           "Industry": "Pharmaceuticals",    "Annual_Revenue": 870000000.0, "Employees": 3200, "Owner": {"id": "zh-usr01"}},
    {"id": "zh-ac004", "Account_Name": "Sagepoint Consulting",   "Industry": "Professional Services","Annual_Revenue": 48000000.0, "Employees": 220,  "Owner": {"id": "zh-usr03"}},
    {"id": "zh-ac005", "Account_Name": "Vantage Data Corp",      "Industry": "Technology",         "Annual_Revenue": 112000000.0, "Employees": 560,  "Owner": {"id": "zh-usr02"}},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "contact": _MOCK_CONTACTS,
    "account": _MOCK_ACCOUNTS,
}


class ZohoMockConnector(ConnectorBase):
    """Mock Zoho CRM connector."""

    CONNECTOR_ID = "zoho"
    DISPLAY_NAME = "Zoho CRM"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="contact",
                display_name="Zoho Contacts",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_CONTACTS),
                fields=["id", "Full_Name", "Email", "Title", "Department", "Account_Name", "Lead_Status"],
            ),
            EntitySchema(
                entity_type="account",
                display_name="Zoho Accounts",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_ACCOUNTS),
                fields=["id", "Account_Name", "Industry", "Annual_Revenue", "Employees", "Owner"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Zoho connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            email = raw.get("Email")
            name = raw.get("Full_Name") or raw.get("Account_Name", "")
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["id"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=email,
                name_hint=name,
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        all_records = list(_ENTITY_DATA.get(entity_type, []))
        changed = [r for r in all_records if random.random() < 0.20]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                email = raw.get("Email")
                name = raw.get("Full_Name") or raw.get("Account_Name", "")
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=raw["id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=email,
                    name_hint=name,
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
            latency_ms=43.0,
        )
