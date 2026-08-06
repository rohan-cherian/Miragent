"""
scout/connectors/mock/bamboohr.py — Mock BambooHR HCM connector.

BambooHR is a popular HRIS for SMB/mid-market companies.
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
    {"employeeId": "BHR-001", "firstName": "Claire",   "lastName": "Hartwell",   "workEmail": "c.hartwell@ridgelinecap.com",  "jobTitle": "Chief People Officer",     "department": "People Operations", "supervisorId": None,      "employmentStatus": "Active",   "hireDate": "2019-08-12", "location": "New York"},
    {"employeeId": "BHR-002", "firstName": "Nathan",   "lastName": "Okafor",     "workEmail": "n.okafor@ridgelinecap.com",    "jobTitle": "HR Business Partner",      "department": "People Operations", "supervisorId": "BHR-001", "employmentStatus": "Active",   "hireDate": "2021-03-01", "location": "New York"},
    {"employeeId": "BHR-003", "firstName": "Sophia",   "lastName": "Mancini",    "workEmail": "s.mancini@ridgelinecap.com",   "jobTitle": "Talent Acquisition Lead",  "department": "People Operations", "supervisorId": "BHR-001", "employmentStatus": "Active",   "hireDate": "2021-09-15", "location": "Chicago"},
    {"employeeId": "BHR-004", "firstName": "Derek",    "lastName": "Tran",       "workEmail": "d.tran@ridgelinecap.com",      "jobTitle": "VP of Finance",            "department": "Finance",           "supervisorId": None,      "employmentStatus": "Active",   "hireDate": "2018-05-07", "location": "New York"},
    {"employeeId": "BHR-005", "firstName": "Amara",    "lastName": "Osei",       "workEmail": "a.osei@ridgelinecap.com",      "jobTitle": "Senior Financial Analyst", "department": "Finance",           "supervisorId": "BHR-004", "employmentStatus": "Active",   "hireDate": "2022-01-10", "location": "New York"},
    {"employeeId": "BHR-006", "firstName": "Marcus",   "lastName": "Delacroix",  "workEmail": "m.delacroix@ridgelinecap.com", "jobTitle": "Financial Analyst",        "department": "Finance",           "supervisorId": "BHR-004", "employmentStatus": "Active",   "hireDate": "2022-07-18", "location": "Austin"},
    {"employeeId": "BHR-007", "firstName": "Leila",    "lastName": "Nazari",     "workEmail": "l.nazari@ridgelinecap.com",    "jobTitle": "Head of Marketing",        "department": "Marketing",         "supervisorId": None,      "employmentStatus": "Active",   "hireDate": "2020-02-24", "location": "San Francisco"},
    {"employeeId": "BHR-008", "firstName": "Justin",   "lastName": "Park",       "workEmail": "j.park@ridgelinecap.com",      "jobTitle": "Marketing Manager",        "department": "Marketing",         "supervisorId": "BHR-007", "employmentStatus": "Active",   "hireDate": "2023-04-03", "location": "San Francisco"},
    {"employeeId": "BHR-009", "firstName": "Brianna",  "lastName": "Kowalski",   "workEmail": "b.kowalski@ridgelinecap.com",  "jobTitle": "Content Strategist",       "department": "Marketing",         "supervisorId": "BHR-007", "employmentStatus": "Inactive", "hireDate": "2021-11-29", "location": "Remote"},
    {"employeeId": "BHR-010", "firstName": "Ethan",    "lastName": "Guerrero",   "workEmail": "e.guerrero@ridgelinecap.com",  "jobTitle": "IT Systems Administrator", "department": "IT",                "supervisorId": None,      "employmentStatus": "Active",   "hireDate": "2020-06-15", "location": "New York"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "employee": _MOCK_EMPLOYEES,
}


class BambooHRMockConnector(ConnectorBase):
    """Mock BambooHR HCM connector."""

    CONNECTOR_ID = "bamboohr"
    DISPLAY_NAME = "BambooHR"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="employee",
                display_name="BambooHR Employees",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_EMPLOYEES),
                fields=["employeeId", "firstName", "lastName", "workEmail", "jobTitle", "department", "supervisorId", "employmentStatus", "hireDate", "location"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"BambooHR connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["employeeId"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("workEmail"),
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
                    source_id=raw["employeeId"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("workEmail"),
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
            latency_ms=45.0,
        )
