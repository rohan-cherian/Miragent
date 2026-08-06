"""
scout/connectors/mock/freshservice.py — Mock Freshservice ITSM connector.

Freshservice is an IT service management platform by Freshworks.
Entity types: user
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

_MOCK_USERS = [
    {"id": 7001, "first_name": "Sarah",    "last_name": "Chen",         "email": "s.chen@acmecorp.com",          "job_title": "VP of Sales",            "department_id": 801, "department": "Sales",       "reporting_manager_id": None, "active": True,  "created_at": "2021-03-15T00:00:00Z"},
    {"id": 7002, "first_name": "Raj",      "last_name": "Krishnamurthy","email": "r.krishnamurthy@acmecorp.com",  "job_title": "VP of Engineering",      "department_id": 802, "department": "Engineering", "reporting_manager_id": None, "active": True,  "created_at": "2020-06-01T00:00:00Z"},
    {"id": 7003, "first_name": "Amanda",   "last_name": "Foster",       "email": "a.foster@acmecorp.com",         "job_title": "CFO",                    "department_id": 803, "department": "Finance",     "reporting_manager_id": None, "active": True,  "created_at": "2019-11-01T00:00:00Z"},
    {"id": 7004, "first_name": "Elena",    "last_name": "Vasquez",      "email": "e.vasquez@acmecorp.com",        "job_title": "Engineering Manager",    "department_id": 802, "department": "Engineering", "reporting_manager_id": 7002, "active": True,  "created_at": "2021-02-01T00:00:00Z"},
    {"id": 7005, "first_name": "James",    "last_name": "Liu",          "email": "j.liu@acmecorp.com",            "job_title": "Senior Software Engineer","department_id": 802, "department": "Engineering", "reporting_manager_id": 7004, "active": True,  "created_at": "2021-05-10T00:00:00Z"},
    {"id": 7006, "first_name": "Marcus",   "last_name": "Johnson",      "email": "m.johnson@acmecorp.com",        "job_title": "Account Executive",      "department_id": 801, "department": "Sales",       "reporting_manager_id": 7001, "active": True,  "created_at": "2022-06-01T00:00:00Z"},
    {"id": 7007, "first_name": "Lisa",     "last_name": "Nakamura",     "email": "l.nakamura@acmecorp.com",       "job_title": "Director of FP&A",       "department_id": 803, "department": "Finance",     "reporting_manager_id": 7003, "active": True,  "created_at": "2021-11-01T00:00:00Z"},
    {"id": 7008, "first_name": "Thomas",   "last_name": "Brennan",      "email": "t.brennan@acmecorp.com",        "job_title": "Senior Accountant",      "department_id": 803, "department": "Finance",     "reporting_manager_id": 7007, "active": False, "created_at": "2021-05-15T00:00:00Z"},
    {"id": 7009, "first_name": "David",    "last_name": "Kim",          "email": "d.kim@acmecorp.com",            "job_title": "Sales Engineer",         "department_id": 801, "department": "Sales",       "reporting_manager_id": 7001, "active": True,  "created_at": "2023-01-10T00:00:00Z"},
    {"id": 7010, "first_name": "Aisha",    "last_name": "Mohammed",     "email": "a.mohammed@acmecorp.com",       "job_title": "Software Engineer",      "department_id": 802, "department": "Engineering", "reporting_manager_id": 7004, "active": True,  "created_at": "2022-03-01T00:00:00Z"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
}


class FreshserviceMockConnector(ConnectorBase):
    """Mock Freshservice ITSM connector."""

    CONNECTOR_ID = "freshservice"
    DISPLAY_NAME = "Freshservice"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Freshservice Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["id", "first_name", "last_name", "email", "job_title", "department_id", "department", "reporting_manager_id", "active", "created_at"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Freshservice connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=str(raw["id"]),
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
        changed = [r for r in all_records if random.random() < 0.10]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=str(raw["id"]),
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("email"),
                    name_hint=f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip(),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"updated_since": datetime.utcnow().isoformat()},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=48.0,
        )
