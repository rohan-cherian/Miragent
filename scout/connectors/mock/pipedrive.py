"""
scout/connectors/mock/pipedrive.py — Mock Pipedrive CRM connector.

Pipedrive CRM for persons and organizations.
Entity types: person, organization
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

_MOCK_PERSONS = [
    {"id": 1001, "name": "Elena Marchetti",   "email": [{"value": "e.marchetti@quantum-bio.com", "primary": True}],   "job_title": "Chief Scientific Officer",   "org_id": 201, "active_flag": True},
    {"id": 1002, "name": "Franco Esposito",   "email": [{"value": "f.esposito@quantum-bio.com", "primary": True}],    "job_title": "Head of R&D",                "org_id": 201, "active_flag": True},
    {"id": 1003, "name": "Anya Petrova",      "email": [{"value": "a.petrova@titan-logistics.com", "primary": True}], "job_title": "VP of Supply Chain",         "org_id": 202, "active_flag": True},
    {"id": 1004, "name": "Bryce Hamilton",    "email": [{"value": "b.hamilton@titan-logistics.com", "primary": True}],"job_title": "Procurement Director",       "org_id": 202, "active_flag": True},
    {"id": 1005, "name": "Mei-Ling Zhou",     "email": [{"value": "m.zhou@brighton-media.com", "primary": True}],     "job_title": "Chief Marketing Officer",    "org_id": 203, "active_flag": True},
    {"id": 1006, "name": "Desmond Okafor",    "email": [{"value": "d.okafor@brighton-media.com", "primary": True}],   "job_title": "Digital Marketing Director", "org_id": 203, "active_flag": False},
    {"id": 1007, "name": "Aurora Lindström",  "email": [{"value": "a.lindstrom@apex-construction.com", "primary": True}],"job_title": "CEO",                   "org_id": 204, "active_flag": True},
    {"id": 1008, "name": "Kieran O'Sullivan", "email": [{"value": "k.osullivan@veritas-law.com", "primary": True}],   "job_title": "Managing Partner",           "org_id": 205, "active_flag": True},
]

_MOCK_ORGANIZATIONS = [
    {"id": 201, "name": "Quantum BioSciences",    "industry": "Biotechnology",       "owner_id": 1001},
    {"id": 202, "name": "Titan Logistics Group",  "industry": "Transportation",      "owner_id": 1003},
    {"id": 203, "name": "Brighton Media Corp",    "industry": "Media & Entertainment","owner_id": 1005},
    {"id": 204, "name": "Apex Construction LLC",  "industry": "Construction",        "owner_id": 1007},
    {"id": 205, "name": "Veritas Law Group",      "industry": "Legal Services",      "owner_id": 1008},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "person": _MOCK_PERSONS,
    "organization": _MOCK_ORGANIZATIONS,
}


class PipedriveMockConnector(ConnectorBase):
    """Mock Pipedrive CRM connector."""

    CONNECTOR_ID = "pipedrive"
    DISPLAY_NAME = "Pipedrive CRM"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="person",
                display_name="Pipedrive Persons",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_PERSONS),
                fields=["id", "name", "email", "job_title", "org_id", "active_flag"],
            ),
            EntitySchema(
                entity_type="organization",
                display_name="Pipedrive Organizations",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_ORGANIZATIONS),
                fields=["id", "name", "industry", "owner_id"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Pipedrive connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            source_id = str(raw["id"])
            # email is a list of objects for persons
            email_list = raw.get("email", [])
            email = next((e["value"] for e in email_list if e.get("primary")), None) if isinstance(email_list, list) else None
            name = raw.get("name", "")
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=source_id,
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
                source_id = str(raw["id"])
                email_list = raw.get("email", [])
                email = next((e["value"] for e in email_list if e.get("primary")), None) if isinstance(email_list, list) else None
                name = raw.get("name", "")
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
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
            latency_ms=32.0,
        )
