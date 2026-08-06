"""
scout/connectors/mock/ukg.py — Mock UKG Pro (Ultimate Kronos Group) HCM connector.

UKG Pro is an enterprise HCM platform for workforce management.
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
    {"personNumber": "UKG-1001", "fullName": "Patricia Holloway",  "emailAddress": "p.holloway@summit-industrial.com",  "jobTitle": "Chief Human Resources Officer",  "orgUnitDescription": "Human Resources",  "supervisorPersonNumber": None,       "employeeStatus": "Active",   "hireDate": "2016-03-14"},
    {"personNumber": "UKG-1002", "fullName": "Darnell Washington",  "emailAddress": "d.washington@summit-industrial.com", "jobTitle": "HR Manager",                    "orgUnitDescription": "Human Resources",  "supervisorPersonNumber": "UKG-1001", "employeeStatus": "Active",   "hireDate": "2019-08-05"},
    {"personNumber": "UKG-1003", "fullName": "Grace Lindqvist",     "emailAddress": "g.lindqvist@summit-industrial.com",  "jobTitle": "HRIS Analyst",                  "orgUnitDescription": "Human Resources",  "supervisorPersonNumber": "UKG-1001", "employeeStatus": "Active",   "hireDate": "2021-05-17"},
    {"personNumber": "UKG-1004", "fullName": "Bernard Okafor",      "emailAddress": "b.okafor@summit-industrial.com",     "jobTitle": "VP of Manufacturing",           "orgUnitDescription": "Manufacturing",    "supervisorPersonNumber": None,       "employeeStatus": "Active",   "hireDate": "2015-11-23"},
    {"personNumber": "UKG-1005", "fullName": "Vanessa Chu",         "emailAddress": "v.chu@summit-industrial.com",        "jobTitle": "Plant Manager",                 "orgUnitDescription": "Manufacturing",    "supervisorPersonNumber": "UKG-1004", "employeeStatus": "Active",   "hireDate": "2018-04-09"},
    {"personNumber": "UKG-1006", "fullName": "Roderick Stein",      "emailAddress": "r.stein@summit-industrial.com",      "jobTitle": "Production Supervisor",         "orgUnitDescription": "Manufacturing",    "supervisorPersonNumber": "UKG-1005", "employeeStatus": "Active",   "hireDate": "2020-01-27"},
    {"personNumber": "UKG-1007", "fullName": "Fatima Al-Hassan",    "emailAddress": "f.alhassan@summit-industrial.com",   "jobTitle": "Quality Control Manager",       "orgUnitDescription": "Quality Assurance","supervisorPersonNumber": "UKG-1004", "employeeStatus": "Active",   "hireDate": "2019-10-14"},
    {"personNumber": "UKG-1008", "fullName": "Charles Petrov",      "emailAddress": "c.petrov@summit-industrial.com",     "jobTitle": "Supply Chain Director",         "orgUnitDescription": "Supply Chain",     "supervisorPersonNumber": None,       "employeeStatus": "Active",   "hireDate": "2017-07-31"},
    {"personNumber": "UKG-1009", "fullName": "Monica Treviño",      "emailAddress": "m.trevino@summit-industrial.com",    "jobTitle": "Procurement Manager",           "orgUnitDescription": "Supply Chain",     "supervisorPersonNumber": "UKG-1008", "employeeStatus": "Inactive", "hireDate": "2020-09-08"},
    {"personNumber": "UKG-1010", "fullName": "Andrew Carmichael",   "emailAddress": "a.carmichael@summit-industrial.com", "jobTitle": "Logistics Coordinator",         "orgUnitDescription": "Supply Chain",     "supervisorPersonNumber": "UKG-1008", "employeeStatus": "Active",   "hireDate": "2022-12-05"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "employee": _MOCK_EMPLOYEES,
}


class UKGMockConnector(ConnectorBase):
    """Mock UKG Pro HCM connector."""

    CONNECTOR_ID = "ukg"
    DISPLAY_NAME = "UKG Pro"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="employee",
                display_name="UKG Employees",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_EMPLOYEES),
                fields=["personNumber", "fullName", "emailAddress", "jobTitle", "orgUnitDescription", "supervisorPersonNumber", "employeeStatus", "hireDate"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"UKG connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["personNumber"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("emailAddress"),
                name_hint=raw.get("fullName"),
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
                    source_id=raw["personNumber"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("emailAddress"),
                    name_hint=raw.get("fullName"),
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
            latency_ms=67.0,
        )
