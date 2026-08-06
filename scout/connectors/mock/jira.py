"""
scout/connectors/mock/jira.py — Mock Jira ITSM connector.

Jira (Atlassian) for project and issue tracking user data.
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
    {"accountId": "jira-u001", "displayName": "Sarah Chen",        "emailAddress": "s.chen@acmecorp.atlassian.net",           "active": True,  "accountType": "atlassian"},
    {"accountId": "jira-u002", "displayName": "Raj Krishnamurthy", "emailAddress": "r.krishnamurthy@acmecorp.atlassian.net",  "active": True,  "accountType": "atlassian"},
    {"accountId": "jira-u003", "displayName": "Elena Vasquez",     "emailAddress": "e.vasquez@acmecorp.atlassian.net",        "active": True,  "accountType": "atlassian"},
    {"accountId": "jira-u004", "displayName": "James Liu",         "emailAddress": "j.liu@acmecorp.atlassian.net",            "active": True,  "accountType": "atlassian"},
    {"accountId": "jira-u005", "displayName": "Aisha Mohammed",    "emailAddress": "a.mohammed@acmecorp.atlassian.net",       "active": True,  "accountType": "atlassian"},
    {"accountId": "jira-u006", "displayName": "Carlos Mendez",     "emailAddress": "c.mendez@acmecorp.atlassian.net",         "active": True,  "accountType": "atlassian"},
    {"accountId": "jira-u007", "displayName": "Jennifer Walsh",    "emailAddress": "j.walsh@acmecorp.atlassian.net",          "active": True,  "accountType": "atlassian"},
    {"accountId": "jira-u008", "displayName": "Thomas Brennan",    "emailAddress": "t.brennan@acmecorp.atlassian.net",        "active": False, "accountType": "atlassian"},
    {"accountId": "jira-u009", "displayName": "CI System Account", "emailAddress": "ci-system@acmecorp.atlassian.net",        "active": True,  "accountType": "app"},
    {"accountId": "jira-u010", "displayName": "David Kim",         "emailAddress": "d.kim@acmecorp.atlassian.net",            "active": True,  "accountType": "atlassian"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
}


class JiraMockConnector(ConnectorBase):
    """Mock Jira ITSM connector."""

    CONNECTOR_ID = "jira"
    DISPLAY_NAME = "Jira"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 10.0  # Jira Cloud allows high rate limits for admins

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Jira Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["accountId", "displayName", "emailAddress", "active", "accountType"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Jira connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["accountId"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("emailAddress"),
                name_hint=raw.get("displayName"),
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
                    source_id=raw["accountId"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("emailAddress"),
                    name_hint=raw.get("displayName"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"startAt": len(all_records)},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=45.0,
        )
