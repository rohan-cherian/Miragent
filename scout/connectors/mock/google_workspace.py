"""
scout/connectors/mock/google_workspace.py — Mock Google Workspace connector.

Google Workspace (formerly G Suite) directory for users.
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
    {"id": "gws-u001", "primaryEmail": "s.chen@acmecorp.com",          "name": {"fullName": "Sarah Chen",        "givenName": "Sarah",    "familyName": "Chen"},        "orgUnitPath": "/Sales",       "organizations": [{"title": "VP of Sales",            "department": "Sales"}],       "relations": [{"value": "a.foster@acmecorp.com"}],   "suspended": False, "creationTime": "2021-03-15T00:00:00Z"},
    {"id": "gws-u002", "primaryEmail": "r.krishnamurthy@acmecorp.com",  "name": {"fullName": "Raj Krishnamurthy", "givenName": "Raj",      "familyName": "Krishnamurthy"},"orgUnitPath": "/Engineering", "organizations": [{"title": "VP of Engineering",      "department": "Engineering"}], "relations": [{"value": "a.foster@acmecorp.com"}],   "suspended": False, "creationTime": "2020-06-01T00:00:00Z"},
    {"id": "gws-u003", "primaryEmail": "a.foster@acmecorp.com",         "name": {"fullName": "Amanda Foster",     "givenName": "Amanda",   "familyName": "Foster"},      "orgUnitPath": "/Finance",     "organizations": [{"title": "CFO",                    "department": "Finance"}],     "relations": [],                                     "suspended": False, "creationTime": "2019-11-01T00:00:00Z"},
    {"id": "gws-u004", "primaryEmail": "m.johnson@acmecorp.com",        "name": {"fullName": "Marcus Johnson",    "givenName": "Marcus",   "familyName": "Johnson"},     "orgUnitPath": "/Sales",       "organizations": [{"title": "Account Executive",      "department": "Sales"}],       "relations": [{"value": "s.chen@acmecorp.com"}],     "suspended": False, "creationTime": "2022-06-01T00:00:00Z"},
    {"id": "gws-u005", "primaryEmail": "p.patel@acmecorp.com",          "name": {"fullName": "Priya Patel",       "givenName": "Priya",    "familyName": "Patel"},       "orgUnitPath": "/Sales",       "organizations": [{"title": "Account Executive",      "department": "Sales"}],       "relations": [{"value": "s.chen@acmecorp.com"}],     "suspended": False, "creationTime": "2022-08-15T00:00:00Z"},
    {"id": "gws-u006", "primaryEmail": "e.vasquez@acmecorp.com",        "name": {"fullName": "Elena Vasquez",     "givenName": "Elena",    "familyName": "Vasquez"},     "orgUnitPath": "/Engineering", "organizations": [{"title": "Engineering Manager",    "department": "Engineering"}], "relations": [{"value": "r.krishnamurthy@acmecorp.com"}],"suspended": False,"creationTime": "2021-02-01T00:00:00Z"},
    {"id": "gws-u007", "primaryEmail": "j.liu@acmecorp.com",            "name": {"fullName": "James Liu",         "givenName": "James",    "familyName": "Liu"},         "orgUnitPath": "/Engineering", "organizations": [{"title": "Senior Software Engineer","department": "Engineering"}], "relations": [{"value": "e.vasquez@acmecorp.com"}],  "suspended": False, "creationTime": "2021-05-10T00:00:00Z"},
    {"id": "gws-u008", "primaryEmail": "a.mohammed@acmecorp.com",       "name": {"fullName": "Aisha Mohammed",    "givenName": "Aisha",    "familyName": "Mohammed"},    "orgUnitPath": "/Engineering", "organizations": [{"title": "Software Engineer",      "department": "Engineering"}], "relations": [{"value": "e.vasquez@acmecorp.com"}],  "suspended": False, "creationTime": "2022-03-01T00:00:00Z"},
    {"id": "gws-u009", "primaryEmail": "l.nakamura@acmecorp.com",       "name": {"fullName": "Lisa Nakamura",     "givenName": "Lisa",     "familyName": "Nakamura"},    "orgUnitPath": "/Finance",     "organizations": [{"title": "Director of FP&A",       "department": "Finance"}],     "relations": [{"value": "a.foster@acmecorp.com"}],   "suspended": False, "creationTime": "2021-11-01T00:00:00Z"},
    {"id": "gws-u010", "primaryEmail": "t.brennan@acmecorp.com",        "name": {"fullName": "Thomas Brennan",    "givenName": "Thomas",   "familyName": "Brennan"},     "orgUnitPath": "/Finance",     "organizations": [{"title": "Senior Accountant",      "department": "Finance"}],     "relations": [{"value": "l.nakamura@acmecorp.com"}], "suspended": True,  "creationTime": "2021-05-15T00:00:00Z"},
    {"id": "gws-u011", "primaryEmail": "d.kim@acmecorp.com",            "name": {"fullName": "David Kim",         "givenName": "David",    "familyName": "Kim"},         "orgUnitPath": "/Sales",       "organizations": [{"title": "Sales Engineer",         "department": "Sales"}],       "relations": [{"value": "s.chen@acmecorp.com"}],     "suspended": False, "creationTime": "2023-01-10T00:00:00Z"},
    {"id": "gws-u012", "primaryEmail": "c.mendez@acmecorp.com",         "name": {"fullName": "Carlos Mendez",     "givenName": "Carlos",   "familyName": "Mendez"},      "orgUnitPath": "/Engineering", "organizations": [{"title": "Software Engineer",      "department": "Engineering"}], "relations": [{"value": "e.vasquez@acmecorp.com"}],  "suspended": False, "creationTime": "2023-06-01T00:00:00Z"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
}


class GoogleWorkspaceMockConnector(ConnectorBase):
    """Mock Google Workspace Directory connector."""

    CONNECTOR_ID = "google_workspace"
    DISPLAY_NAME = "Google Workspace"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 5.0  # Google Workspace Admin SDK rate limit

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Google Workspace Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["id", "primaryEmail", "name", "orgUnitPath", "organizations", "relations", "suspended", "creationTime"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Google Workspace connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            name_obj = raw.get("name", {})
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["id"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("primaryEmail"),
                name_hint=name_obj.get("fullName"),
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
                name_obj = raw.get("name", {})
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=raw["id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("primaryEmail"),
                    name_hint=name_obj.get("fullName"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"pageToken": ""},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=28.0,
        )
