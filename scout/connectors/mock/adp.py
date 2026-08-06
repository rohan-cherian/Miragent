"""
scout/connectors/mock/adp.py — Mock ADP Workforce Now HCM connector.

ADP is a leading payroll and HCM platform.
Entity types: worker
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

_MOCK_WORKERS = [
    {"workerId": "ADP-W001", "fullName": "Raymond Castillo",   "email": "r.castillo@veridian-tech.com",  "positionTitle": "Chief Executive Officer",       "department": "Executive",      "managerId": None,       "workerStatus": "Active",   "startDate": "2017-01-15", "employeeType": "Regular",    "businessUnit": "Corporate"},
    {"workerId": "ADP-W002", "fullName": "Ingrid Sorensen",    "email": "i.sorensen@veridian-tech.com",  "positionTitle": "Chief Technology Officer",      "department": "Technology",     "managerId": "ADP-W001", "workerStatus": "Active",   "startDate": "2018-03-20", "employeeType": "Regular",    "businessUnit": "Technology"},
    {"workerId": "ADP-W003", "fullName": "Felix Yamamoto",     "email": "f.yamamoto@veridian-tech.com",  "positionTitle": "VP of Product",                 "department": "Product",        "managerId": "ADP-W001", "workerStatus": "Active",   "startDate": "2019-07-01", "employeeType": "Regular",    "businessUnit": "Product"},
    {"workerId": "ADP-W004", "fullName": "Dana Whitfield",     "email": "d.whitfield@veridian-tech.com", "positionTitle": "Engineering Manager",           "department": "Engineering",    "managerId": "ADP-W002", "workerStatus": "Active",   "startDate": "2020-02-10", "employeeType": "Regular",    "businessUnit": "Technology"},
    {"workerId": "ADP-W005", "fullName": "Lucas Ferreira",     "email": "l.ferreira@veridian-tech.com",  "positionTitle": "Senior Software Engineer",      "department": "Engineering",    "managerId": "ADP-W004", "workerStatus": "Active",   "startDate": "2020-11-30", "employeeType": "Regular",    "businessUnit": "Technology"},
    {"workerId": "ADP-W006", "fullName": "Priya Balachandran", "email": "p.balachandran@veridian-tech.com","positionTitle": "Software Engineer",            "department": "Engineering",    "managerId": "ADP-W004", "workerStatus": "Active",   "startDate": "2022-04-18", "employeeType": "Regular",    "businessUnit": "Technology"},
    {"workerId": "ADP-W007", "fullName": "Owen Fitzgerald",    "email": "o.fitzgerald@veridian-tech.com", "positionTitle": "DevOps Engineer",              "department": "Engineering",    "managerId": "ADP-W004", "workerStatus": "Active",   "startDate": "2021-08-09", "employeeType": "Contractor", "businessUnit": "Technology"},
    {"workerId": "ADP-W008", "fullName": "Maya Krishnan",      "email": "m.krishnan@veridian-tech.com",  "positionTitle": "Product Manager",               "department": "Product",        "managerId": "ADP-W003", "workerStatus": "Active",   "startDate": "2021-05-24", "employeeType": "Regular",    "businessUnit": "Product"},
    {"workerId": "ADP-W009", "fullName": "Sebastian Novak",    "email": "s.novak@veridian-tech.com",     "positionTitle": "UX Designer",                  "department": "Design",         "managerId": "ADP-W003", "workerStatus": "Active",   "startDate": "2022-09-12", "employeeType": "Regular",    "businessUnit": "Product"},
    {"workerId": "ADP-W010", "fullName": "Tanya Brooks",       "email": "t.brooks@veridian-tech.com",    "positionTitle": "Sales Director",                "department": "Sales",          "managerId": "ADP-W001", "workerStatus": "Inactive",  "startDate": "2019-03-05", "employeeType": "Regular",    "businessUnit": "Revenue"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "worker": _MOCK_WORKERS,
}


class ADPMockConnector(ConnectorBase):
    """Mock ADP Workforce Now HCM connector."""

    CONNECTOR_ID = "adp"
    DISPLAY_NAME = "ADP Workforce Now"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="worker",
                display_name="ADP Workers",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_WORKERS),
                fields=["workerId", "fullName", "email", "positionTitle", "department", "managerId", "workerStatus", "startDate", "employeeType", "businessUnit"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"ADP connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["workerId"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("email"),
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
                    source_id=raw["workerId"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("email"),
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
            latency_ms=52.0,
        )
