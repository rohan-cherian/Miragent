"""
scout/connectors/mock/jumpcloud.py — Mock JumpCloud Identity connector.

JumpCloud is a cloud directory platform for identity management.
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
    {"_id": "jc-u001", "username": "nwilliams",    "email": "n.williams@cloudnative-co.com",   "firstname": "Nicole",    "lastname": "Williams",    "job_title": "Head of IT",            "department": "IT",           "manager": None,          "activated": True,  "account_locked": False},
    {"_id": "jc-u002", "username": "dchang",       "email": "d.chang@cloudnative-co.com",      "firstname": "Daniel",    "lastname": "Chang",       "job_title": "IT Systems Engineer",   "department": "IT",           "manager": "jc-u001",     "activated": True,  "account_locked": False},
    {"_id": "jc-u003", "username": "kmartinez",    "email": "k.martinez@cloudnative-co.com",   "firstname": "Katelyn",   "lastname": "Martinez",    "job_title": "Security Analyst",      "department": "Security",     "manager": "jc-u001",     "activated": True,  "account_locked": False},
    {"_id": "jc-u004", "username": "bthompson",    "email": "b.thompson@cloudnative-co.com",   "firstname": "Brian",     "lastname": "Thompson",    "job_title": "Cloud Infrastructure Lead","department": "Engineering","manager": None,          "activated": True,  "account_locked": False},
    {"_id": "jc-u005", "username": "arobinson",    "email": "a.robinson@cloudnative-co.com",   "firstname": "Angela",    "lastname": "Robinson",    "job_title": "DevOps Engineer",       "department": "Engineering",  "manager": "jc-u004",     "activated": True,  "account_locked": False},
    {"_id": "jc-u006", "username": "smcnulty",     "email": "s.mcnulty@cloudnative-co.com",    "firstname": "Shaun",     "lastname": "McNulty",     "job_title": "Site Reliability Engineer","department": "Engineering","manager": "jc-u004",     "activated": True,  "account_locked": False},
    {"_id": "jc-u007", "username": "crodriguez",   "email": "c.rodriguez@cloudnative-co.com",  "firstname": "Carla",     "lastname": "Rodriguez",   "job_title": "VP of Engineering",     "department": "Engineering",  "manager": None,          "activated": True,  "account_locked": False},
    {"_id": "jc-u008", "username": "tparker",      "email": "t.parker@cloudnative-co.com",     "firstname": "Trevor",    "lastname": "Parker",      "job_title": "Software Engineer",     "department": "Engineering",  "manager": "jc-u007",     "activated": False, "account_locked": True},
    {"_id": "jc-u009", "username": "yliu",         "email": "y.liu@cloudnative-co.com",        "firstname": "Yulia",     "lastname": "Liu",         "job_title": "Backend Engineer",      "department": "Engineering",  "manager": "jc-u007",     "activated": True,  "account_locked": False},
    {"_id": "jc-u010", "username": "mhughes",      "email": "m.hughes@cloudnative-co.com",     "firstname": "Morgan",    "lastname": "Hughes",      "job_title": "Product Manager",       "department": "Product",      "manager": None,          "activated": True,  "account_locked": False},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "user": _MOCK_USERS,
}


class JumpCloudMockConnector(ConnectorBase):
    """Mock JumpCloud Identity connector."""

    CONNECTOR_ID = "jumpcloud"
    DISPLAY_NAME = "JumpCloud"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="JumpCloud Users",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_USERS),
                fields=["_id", "username", "email", "firstname", "lastname", "job_title", "department", "manager", "activated", "account_locked"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"JumpCloud connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["_id"],
                tenant_id=self.tenant_id,
                payload=raw,
                email_hint=raw.get("email"),
                name_hint=f"{raw.get('firstname', '')} {raw.get('lastname', '')}".strip(),
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
                    source_id=raw["_id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("email"),
                    name_hint=f"{raw.get('firstname', '')} {raw.get('lastname', '')}".strip(),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"skip": 0},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=31.0,
        )
