"""
scout/connectors/mock/billcom.py — Mock Bill.com accounts payable connector.

Bill.com is a digital accounts payable/receivable platform.
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
    {"id": "bill-v001", "name": "Squarespace Inc",            "email": "billing@squarespace.com",      "accountType": "Software",           "isActive": True,  "paymentTerm": "Net 30", "balance": 2400.0,  "address": {"city": "New York",     "state": "NY", "country": "US"}},
    {"id": "bill-v002", "name": "Canva Pty Ltd",              "email": "billing@canva.com",            "accountType": "Software",           "isActive": True,  "paymentTerm": "Net 30", "balance": 1200.0,  "address": {"city": "Sydney",       "state": "NSW","country": "AU"}},
    {"id": "bill-v003", "name": "Airtable Inc",               "email": "billing@airtable.com",         "accountType": "Software",           "isActive": True,  "paymentTerm": "Net 30", "balance": 4800.0,  "address": {"city": "San Francisco","state": "CA", "country": "US"}},
    {"id": "bill-v004", "name": "Loom Inc",                   "email": "billing@loom.com",             "accountType": "Software",           "isActive": True,  "paymentTerm": "Net 30", "balance": 600.0,   "address": {"city": "San Francisco","state": "CA", "country": "US"}},
    {"id": "bill-v005", "name": "Rippling Inc",               "email": "billing@rippling.com",         "accountType": "HR Software",        "isActive": True,  "paymentTerm": "Net 30", "balance": 18500.0, "address": {"city": "San Francisco","state": "CA", "country": "US"}},
    {"id": "bill-v006", "name": "Checkr Inc",                 "email": "billing@checkr.com",           "accountType": "Background Checks",  "isActive": True,  "paymentTerm": "Net 30", "balance": 3200.0,  "address": {"city": "San Francisco","state": "CA", "country": "US"}},
    {"id": "bill-v007", "name": "Gong.io Inc",                "email": "billing@gong.io",              "accountType": "Sales Software",     "isActive": True,  "paymentTerm": "Annual", "balance": 52000.0, "address": {"city": "San Francisco","state": "CA", "country": "US"}},
    {"id": "bill-v008", "name": "Clearbit Inc",               "email": "billing@clearbit.com",         "accountType": "Data Enrichment",    "isActive": False, "paymentTerm": "Net 30", "balance": 0.0,     "address": {"city": "San Francisco","state": "CA", "country": "US"}},
    {"id": "bill-v009", "name": "Amplitude Inc",              "email": "billing@amplitude.com",        "accountType": "Analytics",          "isActive": True,  "paymentTerm": "Annual", "balance": 24000.0, "address": {"city": "San Francisco","state": "CA", "country": "US"}},
    {"id": "bill-v010", "name": "Brex Inc",                   "email": "billing@brex.com",             "accountType": "Financial Services", "isActive": True,  "paymentTerm": "Net 30", "balance": 0.0,     "address": {"city": "San Francisco","state": "CA", "country": "US"}},
]

# Add realistic annual_spend values
_ANNUAL_SPEND_MAP = {
    "bill-v001": 28800.0,
    "bill-v002": 14400.0,
    "bill-v003": 57600.0,
    "bill-v004": 7200.0,
    "bill-v005": 222000.0,
    "bill-v006": 38400.0,
    "bill-v007": 52000.0,
    "bill-v008": 24000.0,
    "bill-v009": 24000.0,
    "bill-v010": 0.0,
}

for v in _MOCK_VENDORS:
    v["annual_spend"] = _ANNUAL_SPEND_MAP.get(v["id"], 12000.0)

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
}


class BillcomMockConnector(ConnectorBase):
    """Mock Bill.com accounts payable connector."""

    CONNECTOR_ID = "billcom"
    DISPLAY_NAME = "Bill.com"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Bill.com Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["id", "name", "email", "accountType", "isActive", "paymentTerm", "balance", "address", "annual_spend"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Bill.com connector does not support entity type: {entity_type}")

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
        changed = [r for r in all_records if random.random() < 0.10]

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
            checkpoint={"updatedTime": datetime.utcnow().isoformat()},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=43.0,
        )
