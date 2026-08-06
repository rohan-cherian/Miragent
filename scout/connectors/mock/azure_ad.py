"""
scout/connectors/mock/azure_ad.py — Mock Microsoft Azure Active Directory connector.

Azure AD (now Entra ID) is Microsoft's cloud identity platform.
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
    {"id": "aad-u001", "displayName": "Sarah Chen",        "mail": "s.chen@acmecorp.com",           "userPrincipalName": "s.chen@acmecorp.onmicrosoft.com",           "jobTitle": "VP of Sales",            "department": "Sales",       "managerId": "aad-u099", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2021-03-15T00:00:00Z"},
    {"id": "aad-u002", "displayName": "Raj Krishnamurthy", "mail": "r.krishnamurthy@acmecorp.com",  "userPrincipalName": "r.krishnamurthy@acmecorp.onmicrosoft.com",  "jobTitle": "VP of Engineering",      "department": "Engineering", "managerId": "aad-u099", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2020-06-01T00:00:00Z"},
    {"id": "aad-u003", "displayName": "Amanda Foster",     "mail": "a.foster@acmecorp.com",         "userPrincipalName": "a.foster@acmecorp.onmicrosoft.com",         "jobTitle": "CFO",                    "department": "Finance",     "managerId": "aad-u099", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2019-11-01T00:00:00Z"},
    {"id": "aad-u004", "displayName": "Marcus Johnson",    "mail": "m.johnson@acmecorp.com",        "userPrincipalName": "m.johnson@acmecorp.onmicrosoft.com",        "jobTitle": "Account Executive",      "department": "Sales",       "managerId": "aad-u001", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2022-06-01T00:00:00Z"},
    {"id": "aad-u005", "displayName": "Priya Patel",       "mail": "p.patel@acmecorp.com",          "userPrincipalName": "p.patel@acmecorp.onmicrosoft.com",          "jobTitle": "Account Executive",      "department": "Sales",       "managerId": "aad-u001", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2022-08-15T00:00:00Z"},
    {"id": "aad-u006", "displayName": "Elena Vasquez",     "mail": "e.vasquez@acmecorp.com",        "userPrincipalName": "e.vasquez@acmecorp.onmicrosoft.com",        "jobTitle": "Engineering Manager",    "department": "Engineering", "managerId": "aad-u002", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2021-02-01T00:00:00Z"},
    {"id": "aad-u007", "displayName": "James Liu",         "mail": "j.liu@acmecorp.com",            "userPrincipalName": "j.liu@acmecorp.onmicrosoft.com",            "jobTitle": "Senior Software Engineer","department": "Engineering", "managerId": "aad-u006", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2021-05-10T00:00:00Z"},
    {"id": "aad-u008", "displayName": "Aisha Mohammed",    "mail": "a.mohammed@acmecorp.com",       "userPrincipalName": "a.mohammed@acmecorp.onmicrosoft.com",       "jobTitle": "Software Engineer",      "department": "Engineering", "managerId": "aad-u006", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2022-03-01T00:00:00Z"},
    {"id": "aad-u009", "displayName": "Lisa Nakamura",     "mail": "l.nakamura@acmecorp.com",       "userPrincipalName": "l.nakamura@acmecorp.onmicrosoft.com",       "jobTitle": "Director of FP&A",       "department": "Finance",     "managerId": "aad-u003", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2021-11-01T00:00:00Z"},
    {"id": "aad-u010", "displayName": "Thomas Brennan",    "mail": "t.brennan@acmecorp.com",        "userPrincipalName": "t.brennan@acmecorp.onmicrosoft.com",        "jobTitle": "Senior Accountant",      "department": "Finance",     "managerId": "aad-u009", "accountEnabled": False, "userType": "Member",  "createdDateTime": "2021-05-15T00:00:00Z"},
    {"id": "aad-u011", "displayName": "contractor_ext",    "mail": "ext.contractor@acmecorp.com",   "userPrincipalName": "ext.contractor_corp#EXT#@acmecorp.onmicrosoft.com","jobTitle": "Contract Developer", "department": "Engineering", "managerId": "aad-u006", "accountEnabled": True,  "userType": "Guest",   "createdDateTime": "2023-09-01T00:00:00Z"},
    {"id": "aad-u012", "displayName": "David Kim",         "mail": "d.kim@acmecorp.com",            "userPrincipalName": "d.kim@acmecorp.onmicrosoft.com",            "jobTitle": "Sales Engineer",         "department": "Sales",       "managerId": "aad-u001", "accountEnabled": True,  "userType": "Member",  "createdDateTime": "2023-01-10T00:00:00Z"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
}


class AzureADMockConnector(ConnectorBase):
    """Mock Microsoft Azure Active Directory connector."""

    CONNECTOR_ID = "azure_ad"
    DISPLAY_NAME = "Microsoft Azure AD"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Azure AD Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["id", "displayName", "mail", "userPrincipalName", "jobTitle", "department", "managerId", "accountEnabled", "userType", "createdDateTime"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Azure AD connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["id"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("mail"),
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
                    source_id=raw["id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("mail"),
                    name_hint=raw.get("displayName"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"deltaLink": "https://graph.microsoft.com/v1.0/users/delta?$deltatoken=xyz"},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=35.0,
        )
