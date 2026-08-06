"""
scout/connectors/mock/okta.py — Mock Okta Identity connector.

Okta is the market-leading identity and access management platform.
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
    {"id": "okta-u001", "profile": {"firstName": "Sarah",    "lastName": "Chen",        "email": "s.chen@acmecorp.com",           "login": "s.chen@acmecorp.com",        "title": "VP of Sales",              "department": "Sales",         "managerId": "okta-u099", "mobilePhone": "+1-212-555-0101"}, "status": "ACTIVE",    "created": "2021-03-15T00:00:00Z", "lastLogin": "2024-01-14T09:23:00Z"},
    {"id": "okta-u002", "profile": {"firstName": "Raj",      "lastName": "Krishnamurthy","email": "r.krishnamurthy@acmecorp.com",  "login": "r.krishnamurthy@acmecorp.com","title": "VP of Engineering",         "department": "Engineering",    "managerId": "okta-u099", "mobilePhone": "+1-415-555-0102"}, "status": "ACTIVE",    "created": "2020-06-01T00:00:00Z", "lastLogin": "2024-01-14T08:55:00Z"},
    {"id": "okta-u003", "profile": {"firstName": "Amanda",   "lastName": "Foster",      "email": "a.foster@acmecorp.com",          "login": "a.foster@acmecorp.com",      "title": "CFO",                      "department": "Finance",        "managerId": "okta-u099", "mobilePhone": "+1-212-555-0103"}, "status": "ACTIVE",    "created": "2019-11-01T00:00:00Z", "lastLogin": "2024-01-14T10:30:00Z"},
    {"id": "okta-u004", "profile": {"firstName": "Marcus",   "lastName": "Johnson",     "email": "m.johnson@acmecorp.com",         "login": "m.johnson@acmecorp.com",     "title": "Account Executive",        "department": "Sales",         "managerId": "okta-u001", "mobilePhone": "+1-212-555-0104"}, "status": "ACTIVE",    "created": "2022-06-01T00:00:00Z", "lastLogin": "2024-01-14T08:45:00Z"},
    {"id": "okta-u005", "profile": {"firstName": "Priya",    "lastName": "Patel",       "email": "p.patel@acmecorp.com",           "login": "p.patel@acmecorp.com",       "title": "Account Executive",        "department": "Sales",         "managerId": "okta-u001", "mobilePhone": "+1-312-555-0105"}, "status": "ACTIVE",    "created": "2022-08-15T00:00:00Z", "lastLogin": "2024-01-13T16:30:00Z"},
    {"id": "okta-u006", "profile": {"firstName": "Elena",    "lastName": "Vasquez",     "email": "e.vasquez@acmecorp.com",         "login": "e.vasquez@acmecorp.com",     "title": "Engineering Manager",      "department": "Engineering",   "managerId": "okta-u002", "mobilePhone": "+1-415-555-0106"}, "status": "ACTIVE",    "created": "2021-02-01T00:00:00Z", "lastLogin": "2024-01-14T09:10:00Z"},
    {"id": "okta-u007", "profile": {"firstName": "James",    "lastName": "Liu",         "email": "j.liu@acmecorp.com",             "login": "j.liu@acmecorp.com",         "title": "Senior Software Engineer", "department": "Engineering",   "managerId": "okta-u006", "mobilePhone": "+1-415-555-0107"}, "status": "ACTIVE",    "created": "2021-05-10T00:00:00Z", "lastLogin": "2024-01-14T11:00:00Z"},
    {"id": "okta-u008", "profile": {"firstName": "Aisha",    "lastName": "Mohammed",    "email": "a.mohammed@acmecorp.com",        "login": "a.mohammed@acmecorp.com",    "title": "Software Engineer",        "department": "Engineering",   "managerId": "okta-u006", "mobilePhone": None},                 "status": "ACTIVE",    "created": "2022-03-01T00:00:00Z", "lastLogin": "2024-01-14T14:22:00Z"},
    {"id": "okta-u009", "profile": {"firstName": "Lisa",     "lastName": "Nakamura",    "email": "l.nakamura@acmecorp.com",        "login": "l.nakamura@acmecorp.com",    "title": "Director of FP&A",         "department": "Finance",        "managerId": "okta-u003", "mobilePhone": "+1-212-555-0109"}, "status": "ACTIVE",    "created": "2021-11-01T00:00:00Z", "lastLogin": "2024-01-14T07:30:00Z"},
    {"id": "okta-u010", "profile": {"firstName": "Thomas",   "lastName": "Brennan",     "email": "t.brennan@acmecorp.com",         "login": "t.brennan@acmecorp.com",     "title": "Senior Accountant",        "department": "Finance",        "managerId": "okta-u009", "mobilePhone": "+1-212-555-0110"}, "status": "SUSPENDED", "created": "2021-05-15T00:00:00Z", "lastLogin": "2023-11-01T00:00:00Z"},
    {"id": "okta-u011", "profile": {"firstName": "Carlos",   "lastName": "Mendez",      "email": "c.mendez@acmecorp.com",          "login": "c.mendez@acmecorp.com",      "title": "Software Engineer",        "department": "Engineering",   "managerId": "okta-u006", "mobilePhone": None},                 "status": "ACTIVE",    "created": "2023-06-01T00:00:00Z", "lastLogin": "2024-01-14T13:15:00Z"},
    {"id": "okta-u012", "profile": {"firstName": "David",    "lastName": "Kim",         "email": "d.kim@acmecorp.com",             "login": "d.kim@acmecorp.com",         "title": "Sales Engineer",           "department": "Sales",         "managerId": "okta-u001", "mobilePhone": "+1-415-555-0112"}, "status": "ACTIVE",    "created": "2023-01-10T00:00:00Z", "lastLogin": "2024-01-14T11:00:00Z"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
}


class OktaMockConnector(ConnectorBase):
    """Mock Okta Identity connector."""

    CONNECTOR_ID = "okta"
    DISPLAY_NAME = "Okta Identity"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 10.0  # Okta allows up to 600 req/min

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Okta Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["id", "profile", "status", "created", "lastLogin"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Okta connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            profile = raw.get("profile", {})
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["id"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=profile.get("email"),
                name_hint=f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
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
                profile = raw.get("profile", {})
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=raw["id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=profile.get("email"),
                    name_hint=f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
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
            latency_ms=22.0,
        )
