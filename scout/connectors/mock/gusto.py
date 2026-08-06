"""
scout/connectors/mock/gusto.py — Mock Gusto HCM connector.

Gusto is a cloud HR, benefits, and payroll platform popular with SMBs.
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
    {"uuid": "gst-e001-aa11", "first_name": "Samantha",  "last_name": "Rivers",      "email": "samantha.rivers@clearpath-advisory.com",   "job_title": "Managing Partner",           "department": "Leadership",   "manager_uuid": None,          "start_date": "2015-06-01", "employment_type": "Full-Time"},
    {"uuid": "gst-e002-bb22", "first_name": "Tobias",    "last_name": "Engel",        "email": "tobias.engel@clearpath-advisory.com",       "job_title": "Senior Partner",             "department": "Advisory",     "manager_uuid": "gst-e001-aa11","start_date": "2017-09-11", "employment_type": "Full-Time"},
    {"uuid": "gst-e003-cc33", "first_name": "Celeste",   "last_name": "Fontaine",     "email": "celeste.fontaine@clearpath-advisory.com",   "job_title": "Associate Partner",          "department": "Advisory",     "manager_uuid": "gst-e001-aa11","start_date": "2019-04-14", "employment_type": "Full-Time"},
    {"uuid": "gst-e004-dd44", "first_name": "Marco",     "last_name": "Esposito",     "email": "marco.esposito@clearpath-advisory.com",     "job_title": "Senior Consultant",          "department": "Advisory",     "manager_uuid": "gst-e002-bb22","start_date": "2020-08-03", "employment_type": "Full-Time"},
    {"uuid": "gst-e005-ee55", "first_name": "Jocelyn",   "last_name": "Fairbanks",    "email": "jocelyn.fairbanks@clearpath-advisory.com",  "job_title": "Consultant",                 "department": "Advisory",     "manager_uuid": "gst-e003-cc33","start_date": "2021-11-15", "employment_type": "Full-Time"},
    {"uuid": "gst-e006-ff66", "first_name": "Hassan",    "last_name": "El-Amin",      "email": "hassan.elamin@clearpath-advisory.com",      "job_title": "Research Analyst",           "department": "Research",     "manager_uuid": "gst-e002-bb22","start_date": "2022-06-20", "employment_type": "Full-Time"},
    {"uuid": "gst-e007-gg77", "first_name": "Bridget",   "last_name": "Callahan",     "email": "bridget.callahan@clearpath-advisory.com",   "job_title": "Office Manager",             "department": "Operations",   "manager_uuid": "gst-e001-aa11","start_date": "2018-01-08", "employment_type": "Full-Time"},
    {"uuid": "gst-e008-hh88", "first_name": "Kwame",     "last_name": "Asante",       "email": "kwame.asante@clearpath-advisory.com",       "job_title": "Financial Controller",       "department": "Finance",      "manager_uuid": "gst-e001-aa11","start_date": "2020-03-02", "employment_type": "Full-Time"},
    {"uuid": "gst-e009-ii99", "first_name": "Natalia",   "last_name": "Varga",        "email": "natalia.varga@clearpath-advisory.com",      "job_title": "Junior Consultant",          "department": "Advisory",     "manager_uuid": "gst-e003-cc33","start_date": "2023-09-04", "employment_type": "Full-Time"},
    {"uuid": "gst-e010-jj00", "first_name": "Trevor",    "last_name": "Lashley",      "email": "trevor.lashley@clearpath-advisory.com",     "job_title": "Freelance Researcher",       "department": "Research",     "manager_uuid": "gst-e002-bb22","start_date": "2023-01-16", "employment_type": "Part-Time"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "employee": _MOCK_EMPLOYEES,
}


class GustoMockConnector(ConnectorBase):
    """Mock Gusto HCM connector."""

    CONNECTOR_ID = "gusto"
    DISPLAY_NAME = "Gusto"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="employee",
                display_name="Gusto Employees",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_EMPLOYEES),
                fields=["uuid", "first_name", "last_name", "email", "job_title", "department", "manager_uuid", "start_date", "employment_type"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Gusto connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["uuid"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("email"),
                name_hint=f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip(),
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
                    source_id=raw["uuid"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("email"),
                    name_hint=f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip(),
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
            latency_ms=41.0,
        )
