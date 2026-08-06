"""
scout/connectors/mock/brex.py — Mock Brex corporate card connector.

Brex is a corporate card and spend management platform for startups/growth companies.
Entity types: vendor
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

_MOCK_VENDORS = [
    {"id": "brx-v001", "name": "Google Cloud Platform",   "category": "Cloud Infrastructure", "total_spend": 1420000.0, "last_transaction_date": "2024-01-14", "payment_method": "Brex Card"},
    {"id": "brx-v002", "name": "GitHub Inc",              "category": "Software",             "total_spend": 48000.0,   "last_transaction_date": "2024-01-01", "payment_method": "Brex Card"},
    {"id": "brx-v003", "name": "Figma Inc",               "category": "Software",             "total_spend": 24000.0,   "last_transaction_date": "2024-01-01", "payment_method": "Brex Card"},
    {"id": "brx-v004", "name": "OpenAI Inc",              "category": "AI Services",          "total_spend": 185000.0,  "last_transaction_date": "2024-01-12", "payment_method": "Brex Card"},
    {"id": "brx-v005", "name": "Linear App",              "category": "Software",             "total_spend": 12000.0,   "last_transaction_date": "2024-01-01", "payment_method": "Brex Card"},
    {"id": "brx-v006", "name": "Notion Labs Inc",         "category": "Software",             "total_spend": 18000.0,   "last_transaction_date": "2024-01-01", "payment_method": "Brex Card"},
    {"id": "brx-v007", "name": "The Trade Desk Inc",      "category": "Advertising",          "total_spend": 95000.0,   "last_transaction_date": "2024-01-10", "payment_method": "Brex Card"},
    {"id": "brx-v008", "name": "SendGrid / Twilio",       "category": "Communications",       "total_spend": 42000.0,   "last_transaction_date": "2024-01-05", "payment_method": "ACH"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
}


class BrexMockConnector(ConnectorBase):
    """Mock Brex corporate card connector."""

    CONNECTOR_ID = "brex"
    DISPLAY_NAME = "Brex"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Brex Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["id", "name", "category", "total_spend", "last_transaction_date", "payment_method"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Brex connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["id"],
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=raw.get("name"),
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        all_records = list(_ENTITY_DATA.get(entity_type, []))
        changed = [r for r in all_records if random.random() < 0.15]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=raw["id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=raw.get("name"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"cursor": ""},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=24.0,
        )
