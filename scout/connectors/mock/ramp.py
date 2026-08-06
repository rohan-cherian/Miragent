"""
scout/connectors/mock/ramp.py — Mock Ramp corporate card connector.

Ramp is a modern corporate card and spend management platform.
Entity types: merchant, transaction
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

_MOCK_MERCHANTS = [
    {"id": "rmp-m001", "name": "Amazon Web Services",   "category_code": "7372", "category_name": "Computer and Data Processing Services", "total_spend_ytd": 892000.0},
    {"id": "rmp-m002", "name": "United Airlines",        "category_code": "4511", "category_name": "Airlines",                             "total_spend_ytd": 145000.0},
    {"id": "rmp-m003", "name": "Marriott Hotels",        "category_code": "7011", "category_name": "Hotels and Motels",                    "total_spend_ytd": 98000.0},
    {"id": "rmp-m004", "name": "Uber for Business",      "category_code": "4111", "category_name": "Transportation",                       "total_spend_ytd": 62000.0},
    {"id": "rmp-m005", "name": "Slack Technologies",     "category_code": "7372", "category_name": "Computer and Data Processing Services", "total_spend_ytd": 84000.0},
    {"id": "rmp-m006", "name": "Zoom Video Comm",        "category_code": "7372", "category_name": "Computer and Data Processing Services", "total_spend_ytd": 36000.0},
    {"id": "rmp-m007", "name": "Instacart Business",     "category_code": "5411", "category_name": "Grocery Stores",                       "total_spend_ytd": 18000.0},
    {"id": "rmp-m008", "name": "Delta Air Lines",        "category_code": "4511", "category_name": "Airlines",                             "total_spend_ytd": 112000.0},
]

_MOCK_TRANSACTIONS = [
    {"id": "rmp-t001", "merchant_id": "rmp-m001", "amount": 74500.0,  "currency_code": "USD", "user_id": "rmp-usr001", "memo": "AWS - Monthly Usage Dec 2023",       "date": "2024-01-01"},
    {"id": "rmp-t002", "merchant_id": "rmp-m002", "amount": 1240.0,   "currency_code": "USD", "user_id": "rmp-usr002", "memo": "Flight SFO-NYC Sales Mtg",           "date": "2024-01-05"},
    {"id": "rmp-t003", "merchant_id": "rmp-m003", "amount": 628.0,    "currency_code": "USD", "user_id": "rmp-usr002", "memo": "Hotel NYC Sales Conference",          "date": "2024-01-06"},
    {"id": "rmp-t004", "merchant_id": "rmp-m004", "amount": 48.0,     "currency_code": "USD", "user_id": "rmp-usr003", "memo": "Airport to Office",                  "date": "2024-01-08"},
    {"id": "rmp-t005", "merchant_id": "rmp-m005", "amount": 7000.0,   "currency_code": "USD", "user_id": "rmp-usr001", "memo": "Slack Business+ Jan 2024",           "date": "2024-01-02"},
    {"id": "rmp-t006", "merchant_id": "rmp-m001", "amount": 82200.0,  "currency_code": "USD", "user_id": "rmp-usr001", "memo": "AWS - Monthly Usage Jan 2024",       "date": "2024-02-01"},
    {"id": "rmp-t007", "merchant_id": "rmp-m008", "amount": 895.0,    "currency_code": "USD", "user_id": "rmp-usr004", "memo": "Flight JFK-SFO Customer Visit",      "date": "2024-01-12"},
    {"id": "rmp-t008", "merchant_id": "rmp-m006", "amount": 3000.0,   "currency_code": "USD", "user_id": "rmp-usr001", "memo": "Zoom Business Jan 2024",             "date": "2024-01-03"},
    {"id": "rmp-t009", "merchant_id": "rmp-m003", "amount": 445.0,    "currency_code": "USD", "user_id": "rmp-usr004", "memo": "Hotel SF Customer Meeting",          "date": "2024-01-13"},
    {"id": "rmp-t010", "merchant_id": "rmp-m007", "amount": 320.0,    "currency_code": "USD", "user_id": "rmp-usr003", "memo": "Team Lunch - Eng Offsite",           "date": "2024-01-10"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "merchant": _MOCK_MERCHANTS,
    "transaction": _MOCK_TRANSACTIONS,
}


class RampMockConnector(ConnectorBase):
    """Mock Ramp corporate card connector."""

    CONNECTOR_ID = "ramp"
    DISPLAY_NAME = "Ramp"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="merchant",
                display_name="Ramp Merchants",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_MERCHANTS),
                fields=["id", "name", "category_code", "category_name", "total_spend_ytd"],
            ),
            EntitySchema(
                entity_type="transaction",
                display_name="Ramp Transactions",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_TRANSACTIONS),
                fields=["id", "merchant_id", "amount", "currency_code", "user_id", "memo", "date"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Ramp connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            source_id = raw["id"]
            name = raw.get("name", "")
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=source_id,
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=name if name else None,
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        all_records = list(_ENTITY_DATA.get(entity_type, []))
        changed = [r for r in all_records if random.random() < 0.30]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                source_id = raw["id"]
                name = raw.get("name", "")
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=name if name else None,
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"from_date": datetime.utcnow().date().isoformat()},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=29.0,
        )
