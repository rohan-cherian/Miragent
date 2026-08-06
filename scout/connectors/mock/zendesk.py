"""
scout/connectors/mock/zendesk.py — Mock Zendesk ITSM connector.

Zendesk for customer support user data.
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
    {"id": 9001001, "name": "Sarah Chen",        "email": "s.chen@acmecorp.com",          "role": "admin",  "job_title": "VP of Sales",            "organization_id": 100001, "active": True,  "created_at": "2021-03-15T00:00:00Z", "last_login_at": "2024-01-14T09:23:00Z"},
    {"id": 9001002, "name": "Marcus Johnson",    "email": "m.johnson@acmecorp.com",        "role": "agent",  "job_title": "Account Executive",      "organization_id": 100001, "active": True,  "created_at": "2022-06-01T00:00:00Z", "last_login_at": "2024-01-14T08:45:00Z"},
    {"id": 9001003, "name": "Jennifer Walsh",    "email": "j.walsh@acmecorp.com",          "role": "agent",  "job_title": "Sales Development Rep",  "organization_id": 100001, "active": True,  "created_at": "2023-07-01T00:00:00Z", "last_login_at": "2024-01-12T14:20:00Z"},
    {"id": 9001004, "name": "Elena Vasquez",     "email": "e.vasquez@acmecorp.com",        "role": "agent",  "job_title": "Engineering Manager",    "organization_id": 100002, "active": True,  "created_at": "2021-02-01T00:00:00Z", "last_login_at": "2024-01-14T09:10:00Z"},
    {"id": 9001005, "name": "Lisa Nakamura",     "email": "l.nakamura@acmecorp.com",       "role": "agent",  "job_title": "Director of FP&A",       "organization_id": 100003, "active": True,  "created_at": "2021-11-01T00:00:00Z", "last_login_at": "2024-01-14T07:30:00Z"},
    {"id": 9001006, "name": "Raj Krishnamurthy", "email": "r.krishnamurthy@acmecorp.com",  "role": "admin",  "job_title": "VP of Engineering",      "organization_id": 100002, "active": True,  "created_at": "2020-06-01T00:00:00Z", "last_login_at": "2024-01-14T08:55:00Z"},
    {"id": 9001007, "name": "Amanda Foster",     "email": "a.foster@acmecorp.com",         "role": "admin",  "job_title": "CFO",                    "organization_id": 100003, "active": True,  "created_at": "2019-11-01T00:00:00Z", "last_login_at": "2024-01-14T10:30:00Z"},
    {"id": 9001008, "name": "Thomas Brennan",    "email": "t.brennan@acmecorp.com",        "role": "end-user","job_title": "Senior Accountant",     "organization_id": 100003, "active": False, "created_at": "2021-05-15T00:00:00Z", "last_login_at": "2023-11-01T00:00:00Z"},
    {"id": 9001009, "name": "David Kim",         "email": "d.kim@acmecorp.com",            "role": "agent",  "job_title": "Sales Engineer",         "organization_id": 100001, "active": True,  "created_at": "2023-01-10T00:00:00Z", "last_login_at": "2024-01-14T11:00:00Z"},
    {"id": 9001010, "name": "Carlos Mendez",     "email": "c.mendez@acmecorp.com",         "role": "agent",  "job_title": "Software Engineer",      "organization_id": 100002, "active": True,  "created_at": "2023-06-01T00:00:00Z", "last_login_at": "2024-01-14T13:15:00Z"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
}


class ZendeskMockConnector(ConnectorBase):
    """Mock Zendesk ITSM connector."""

    CONNECTOR_ID = "zendesk"
    DISPLAY_NAME = "Zendesk"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Zendesk Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["id", "name", "email", "role", "job_title", "organization_id", "active", "created_at", "last_login_at"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Zendesk connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=str(raw["id"]),
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("email"),
                name_hint=raw.get("name"),
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
                    name_hint=raw.get("name"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"start_time": int(datetime.utcnow().timestamp())},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=52.0,
        )
