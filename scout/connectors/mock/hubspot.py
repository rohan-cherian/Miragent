"""
scout/connectors/mock/hubspot.py — Mock HubSpot CRM connector.

HubSpot CRM for contacts and companies.
Entity types: contact, company
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
    {"id": "hs-c001", "firstname": "Katherine",  "lastname": "Brennan",    "email": "k.brennan@northstarcapital.com",    "jobtitle": "Chief Financial Officer",      "department": "Finance",     "associatedcompanyid": "hs-co001", "hs_lead_status": "QUALIFIED"},
    {"id": "hs-c002", "firstname": "Oliver",      "lastname": "Ramsay",     "email": "o.ramsay@northstarcapital.com",     "jobtitle": "VP of Finance",                "department": "Finance",     "associatedcompanyid": "hs-co001", "hs_lead_status": "CONNECTED"},
    {"id": "hs-c003", "firstname": "Simone",      "lastname": "Beaumont",   "email": "s.beaumont@meridianlogistics.com",  "jobtitle": "Director of Procurement",      "department": "Procurement", "associatedcompanyid": "hs-co002", "hs_lead_status": "OPEN"},
    {"id": "hs-c004", "firstname": "Rafael",      "lastname": "Monteiro",   "email": "r.monteiro@meridianlogistics.com",  "jobtitle": "Procurement Manager",          "department": "Procurement", "associatedcompanyid": "hs-co002", "hs_lead_status": "OPEN"},
    {"id": "hs-c005", "firstname": "Yuki",        "lastname": "Tanaka",     "email": "y.tanaka@alphahealth.com",          "jobtitle": "Chief Technology Officer",     "department": "Technology",  "associatedcompanyid": "hs-co003", "hs_lead_status": "QUALIFIED"},
    {"id": "hs-c006", "firstname": "Cameron",     "lastname": "Voss",       "email": "c.voss@alphahealth.com",            "jobtitle": "VP of Engineering",            "department": "Engineering", "associatedcompanyid": "hs-co003", "hs_lead_status": "CONNECTED"},
    {"id": "hs-c007", "firstname": "Denise",      "lastname": "Quarterman", "email": "d.quarterman@stellarretail.com",   "jobtitle": "Chief Operating Officer",      "department": "Operations",  "associatedcompanyid": "hs-co004", "hs_lead_status": "OPEN"},
    {"id": "hs-c008", "firstname": "Harris",      "lastname": "Adeyemi",    "email": "h.adeyemi@pacificgrowth.com",       "jobtitle": "Managing Director",            "department": "Executive",   "associatedcompanyid": "hs-co005", "hs_lead_status": "UNQUALIFIED"},
]

_MOCK_COMPANIES = [
    {"id": "hs-co001", "name": "NorthStar Capital",      "industry": "Financial Services",  "annualrevenue": 52000000,  "numberofemployees": 280,  "ownerId": "hs-c001"},
    {"id": "hs-co002", "name": "Meridian Logistics",     "industry": "Transportation",      "annualrevenue": 88000000,  "numberofemployees": 540,  "ownerId": "hs-c003"},
    {"id": "hs-co003", "name": "Alpha Health Systems",   "industry": "Healthcare",          "annualrevenue": 215000000, "numberofemployees": 1420, "ownerId": "hs-c005"},
    {"id": "hs-co004", "name": "Stellar Retail Group",   "industry": "Retail",              "annualrevenue": 73000000,  "numberofemployees": 620,  "ownerId": "hs-c007"},
    {"id": "hs-co005", "name": "Pacific Growth Partners","industry": "Private Equity",      "annualrevenue": 340000000, "numberofemployees": 95,   "ownerId": "hs-c008"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "contact": _MOCK_CONTACTS,
    "company": _MOCK_COMPANIES,
}


class HubSpotMockConnector(ConnectorBase):
    """Mock HubSpot CRM connector."""

    CONNECTOR_ID = "hubspot"
    DISPLAY_NAME = "HubSpot CRM"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="contact",
                display_name="HubSpot Contacts",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_CONTACTS),
                fields=["id", "firstname", "lastname", "email", "jobtitle", "department", "associatedcompanyid", "hs_lead_status"],
            ),
            EntitySchema(
                entity_type="company",
                display_name="HubSpot Companies",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_COMPANIES),
                fields=["id", "name", "industry", "annualrevenue", "numberofemployees", "ownerId"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"HubSpot connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            email = raw.get("email")
            name = raw.get("name") or f"{raw.get('firstname', '')} {raw.get('lastname', '')}".strip()
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
                email = raw.get("email")
                name = raw.get("name") or f"{raw.get('firstname', '')} {raw.get('lastname', '')}".strip()
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
            latency_ms=28.0,
        )
