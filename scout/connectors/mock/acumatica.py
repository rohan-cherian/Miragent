"""
scout/connectors/mock/acumatica.py — Mock Acumatica ERP connector.

Acumatica is a cloud ERP platform for mid-market companies.
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
    {"VendorID": "ACU-V001", "VendorName": "Avalara Inc",           "VendorClass": "SOFTWARE",  "Status": "Active",   "CurrencyID": "USD", "AnnualSpend": 48000.0,  "PaymentMethod": "ACH"},
    {"VendorID": "ACU-V002", "VendorName": "Paychex Inc",           "VendorClass": "PAYROLL",   "Status": "Active",   "CurrencyID": "USD", "AnnualSpend": 185000.0, "PaymentMethod": "ACH"},
    {"VendorID": "ACU-V003", "VendorName": "Box Inc",               "VendorClass": "SOFTWARE",  "Status": "Active",   "CurrencyID": "USD", "AnnualSpend": 36000.0,  "PaymentMethod": "Credit Card"},
    {"VendorID": "ACU-V004", "VendorName": "Grant Thornton LLP",    "VendorClass": "ADVISORY",  "Status": "Active",   "CurrencyID": "USD", "AnnualSpend": 320000.0, "PaymentMethod": "Wire"},
    {"VendorID": "ACU-V005", "VendorName": "Pitney Bowes Inc",      "VendorClass": "OFFICE",    "Status": "Active",   "CurrencyID": "USD", "AnnualSpend": 22000.0,  "PaymentMethod": "ACH"},
    {"VendorID": "ACU-V006", "VendorName": "Staples Advantage",     "VendorClass": "SUPPLIES",  "Status": "Active",   "CurrencyID": "USD", "AnnualSpend": 28000.0,  "PaymentMethod": "ACH"},
    {"VendorID": "ACU-V007", "VendorName": "Aon Hewitt LLC",        "VendorClass": "INSURANCE", "Status": "Inactive", "CurrencyID": "USD", "AnnualSpend": 95000.0,  "PaymentMethod": "Wire"},
    {"VendorID": "ACU-V008", "VendorName": "Conduent Business Svcs","VendorClass": "TECHSVC",   "Status": "Active",   "CurrencyID": "USD", "AnnualSpend": 142000.0, "PaymentMethod": "ACH"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
}


class AcumaticaMockConnector(ConnectorBase):
    """Mock Acumatica ERP connector."""

    CONNECTOR_ID = "acumatica"
    DISPLAY_NAME = "Acumatica"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Acumatica Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["VendorID", "VendorName", "VendorClass", "Status", "CurrencyID", "AnnualSpend", "PaymentMethod"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Acumatica connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["VendorID"],
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=raw.get("VendorName"),
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
                    source_id=raw["VendorID"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=raw.get("VendorName"),
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
            latency_ms=58.0,
        )
