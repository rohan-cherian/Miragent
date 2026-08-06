"""
scout/connectors/mock/rippling.py — Mock Rippling HCM connector.

Rippling combines HR, IT, and Finance in one platform.
Entity types: employee
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

_MOCK_EMPLOYEES = [
    {"id": "RPL-001", "firstName": "Alexis",   "lastName": "Drummond",    "email": "alexis.drummond@axiom-ventures.com",   "title": "General Counsel",            "department": "Legal",      "managerId": None,       "employmentType": "Full-Time",  "startDate": "2018-09-10", "workLocation": "New York"},
    {"id": "RPL-002", "firstName": "Jordan",   "lastName": "Blackwood",   "email": "jordan.blackwood@axiom-ventures.com",  "title": "Associate General Counsel",  "department": "Legal",      "managerId": "RPL-001",  "employmentType": "Full-Time",  "startDate": "2021-02-22", "workLocation": "New York"},
    {"id": "RPL-003", "firstName": "Mia",      "lastName": "Johansson",   "email": "mia.johansson@axiom-ventures.com",     "title": "VP of Operations",           "department": "Operations", "managerId": None,       "employmentType": "Full-Time",  "startDate": "2019-04-15", "workLocation": "San Francisco"},
    {"id": "RPL-004", "firstName": "Tyler",    "lastName": "Ogundimu",    "email": "tyler.ogundimu@axiom-ventures.com",    "title": "Operations Manager",         "department": "Operations", "managerId": "RPL-003",  "employmentType": "Full-Time",  "startDate": "2021-07-06", "workLocation": "San Francisco"},
    {"id": "RPL-005", "firstName": "Chloe",    "lastName": "Steinberg",   "email": "chloe.steinberg@axiom-ventures.com",   "title": "Business Analyst",           "department": "Operations", "managerId": "RPL-003",  "employmentType": "Full-Time",  "startDate": "2022-10-31", "workLocation": "Remote"},
    {"id": "RPL-006", "firstName": "Victor",   "lastName": "Henriksen",   "email": "victor.henriksen@axiom-ventures.com",  "title": "Head of Customer Success",   "department": "Customer Success", "managerId": None,  "employmentType": "Full-Time",  "startDate": "2020-01-13", "workLocation": "Austin"},
    {"id": "RPL-007", "firstName": "Nina",     "lastName": "Kapoor",      "email": "nina.kapoor@axiom-ventures.com",       "title": "Customer Success Manager",   "department": "Customer Success", "managerId": "RPL-006", "employmentType": "Full-Time", "startDate": "2022-03-28", "workLocation": "Austin"},
    {"id": "RPL-008", "firstName": "Aaron",    "lastName": "Whitmore",    "email": "aaron.whitmore@axiom-ventures.com",    "title": "Customer Success Associate", "department": "Customer Success", "managerId": "RPL-006", "employmentType": "Part-Time", "startDate": "2023-08-14", "workLocation": "Remote"},
    {"id": "RPL-009", "firstName": "Isabelle", "lastName": "Marchand",    "email": "isabelle.marchand@axiom-ventures.com", "title": "Accountant",                 "department": "Finance",    "managerId": None,       "employmentType": "Full-Time",  "startDate": "2021-06-21", "workLocation": "New York"},
    {"id": "RPL-010", "firstName": "Kevin",    "lastName": "Obi",         "email": "kevin.obi@axiom-ventures.com",         "title": "Accounts Payable Specialist","department": "Finance",    "managerId": "RPL-009",  "employmentType": "Contractor", "startDate": "2023-01-09", "workLocation": "Remote"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "employee": _MOCK_EMPLOYEES,
}


class RipplingMockConnector(ConnectorBase):
    """Mock Rippling HCM connector."""

    CONNECTOR_ID = "rippling"
    DISPLAY_NAME = "Rippling"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="employee",
                display_name="Rippling Employees",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_EMPLOYEES),
                fields=["id", "firstName", "lastName", "email", "title", "department", "managerId", "employmentType", "startDate", "workLocation"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Rippling connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["id"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("email"),
                name_hint=f"{raw.get('firstName', '')} {raw.get('lastName', '')}".strip(),
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        all_records = list(_ENTITY_DATA.get(entity_type, []))
        changed = [r for r in all_records if random.random() < 0.15]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=raw["id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("email"),
                    name_hint=f"{raw.get('firstName', '')} {raw.get('lastName', '')}".strip(),
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
            latency_ms=38.0,
        )
