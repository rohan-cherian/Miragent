"""
scout/connectors/mock/servicenow.py — Mock ServiceNow ITSM connector.

ServiceNow is the leading ITSM platform for enterprise IT operations.
Entity types: user, asset
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
    {"sys_id": "sn-u001", "name": "Sarah Chen",        "email": "s.chen@acmecorp.com",          "title": "VP of Sales",            "department": "Sales",       "manager": {"value": "sn-u099"}, "active": True,  "sys_created_on": "2021-03-15 00:00:00"},
    {"sys_id": "sn-u002", "name": "Raj Krishnamurthy", "email": "r.krishnamurthy@acmecorp.com",  "title": "VP of Engineering",      "department": "Engineering", "manager": {"value": "sn-u099"}, "active": True,  "sys_created_on": "2020-06-01 00:00:00"},
    {"sys_id": "sn-u003", "name": "Elena Vasquez",     "email": "e.vasquez@acmecorp.com",        "title": "Engineering Manager",    "department": "Engineering", "manager": {"value": "sn-u002"}, "active": True,  "sys_created_on": "2021-02-01 00:00:00"},
    {"sys_id": "sn-u004", "name": "James Liu",         "email": "j.liu@acmecorp.com",            "title": "Senior Software Engineer","department": "Engineering", "manager": {"value": "sn-u003"}, "active": True,  "sys_created_on": "2021-05-10 00:00:00"},
    {"sys_id": "sn-u005", "name": "Amanda Foster",     "email": "a.foster@acmecorp.com",         "title": "CFO",                    "department": "Finance",     "manager": {"value": "sn-u099"}, "active": True,  "sys_created_on": "2019-11-01 00:00:00"},
    {"sys_id": "sn-u006", "name": "Lisa Nakamura",     "email": "l.nakamura@acmecorp.com",       "title": "Director of FP&A",       "department": "Finance",     "manager": {"value": "sn-u005"}, "active": True,  "sys_created_on": "2021-11-01 00:00:00"},
    {"sys_id": "sn-u007", "name": "Marcus Johnson",    "email": "m.johnson@acmecorp.com",        "title": "Account Executive",      "department": "Sales",       "manager": {"value": "sn-u001"}, "active": True,  "sys_created_on": "2022-06-01 00:00:00"},
    {"sys_id": "sn-u008", "name": "Thomas Brennan",    "email": "t.brennan@acmecorp.com",        "title": "Senior Accountant",      "department": "Finance",     "manager": {"value": "sn-u006"}, "active": False, "sys_created_on": "2021-05-15 00:00:00"},
    {"sys_id": "sn-u009", "name": "David Kim",         "email": "d.kim@acmecorp.com",            "title": "Sales Engineer",         "department": "Sales",       "manager": {"value": "sn-u001"}, "active": True,  "sys_created_on": "2023-01-10 00:00:00"},
    {"sys_id": "sn-u010", "name": "Aisha Mohammed",    "email": "a.mohammed@acmecorp.com",       "title": "Software Engineer",      "department": "Engineering", "manager": {"value": "sn-u003"}, "active": True,  "sys_created_on": "2022-03-01 00:00:00"},
]

_MOCK_ASSETS = [
    {"sys_id": "sn-a001", "name": "MacBook Pro 16 M3",       "asset_tag": "ASSET-1001", "model_category": "Computer",     "assigned_to": {"value": "sn-u004"}, "cost": 3499.0,  "install_status": "In use"},
    {"sys_id": "sn-a002", "name": "MacBook Air 15 M2",        "asset_tag": "ASSET-1002", "model_category": "Computer",     "assigned_to": {"value": "sn-u007"}, "cost": 1799.0,  "install_status": "In use"},
    {"sys_id": "sn-a003", "name": "Dell XPS 15",              "asset_tag": "ASSET-1003", "model_category": "Computer",     "assigned_to": {"value": "sn-u010"}, "cost": 2149.0,  "install_status": "In use"},
    {"sys_id": "sn-a004", "name": "iPhone 15 Pro",            "asset_tag": "ASSET-1004", "model_category": "Mobile",       "assigned_to": {"value": "sn-u001"}, "cost": 999.0,   "install_status": "In use"},
    {"sys_id": "sn-a005", "name": "Cisco IP Phone 8861",      "asset_tag": "ASSET-1005", "model_category": "Phone",        "assigned_to": {"value": "sn-u005"}, "cost": 349.0,   "install_status": "In use"},
    {"sys_id": "sn-a006", "name": "Dell UltraSharp 27\" 4K",  "asset_tag": "ASSET-1006", "model_category": "Monitor",      "assigned_to": {"value": "sn-u002"}, "cost": 699.0,   "install_status": "In use"},
    {"sys_id": "sn-a007", "name": "Cisco Meraki MX67",        "asset_tag": "ASSET-1007", "model_category": "Network",      "assigned_to": None,                  "cost": 2100.0,  "install_status": "Installed"},
    {"sys_id": "sn-a008", "name": "HP LaserJet Enterprise",   "asset_tag": "ASSET-1008", "model_category": "Printer",      "assigned_to": None,                  "cost": 895.0,   "install_status": "Installed"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
    "asset": _MOCK_ASSETS,
}


class ServiceNowMockConnector(ConnectorBase):
    """Mock ServiceNow ITSM connector."""

    CONNECTOR_ID = "servicenow"
    DISPLAY_NAME = "ServiceNow"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="ServiceNow Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["sys_id", "name", "email", "title", "department", "manager", "active", "sys_created_on"],
            ),
            EntitySchema(
                entity_type="asset",
                display_name="ServiceNow Assets",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_ASSETS),
                fields=["sys_id", "name", "asset_tag", "model_category", "assigned_to", "cost", "install_status"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"ServiceNow connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            source_id = raw["sys_id"]
            email = raw.get("email")
            name = raw.get("name")
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
        changed = [r for r in all_records if random.random() < 0.10]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                source_id = raw["sys_id"]
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("email"),
                    name_hint=raw.get("name"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"sys_updated_on": datetime.utcnow().isoformat()},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=118.0,
        )
