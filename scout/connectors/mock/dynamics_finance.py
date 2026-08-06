"""
scout/connectors/mock/dynamics_finance.py — Mock Microsoft Dynamics 365 Finance connector.

Dynamics Finance & Operations for ERP — vendor management.
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
    {"VendorAccountNumber": "DYNF-V001", "VendorName": "Capgemini US LLC",         "VendorGroupId": "CONSULT", "CurrencyCode": "USD", "AnnualSpend": 920000.0,  "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V001"},
    {"VendorAccountNumber": "DYNF-V002", "VendorName": "Oracle America Inc",        "VendorGroupId": "SOFTWR",  "CurrencyCode": "USD", "AnnualSpend": 385000.0,  "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V002"},
    {"VendorAccountNumber": "DYNF-V003", "VendorName": "IBM Corporation",           "VendorGroupId": "TECHSV",  "CurrencyCode": "USD", "AnnualSpend": 650000.0,  "PaymentTermBaseDays": 45, "InvoiceAccount": "DYNF-V003"},
    {"VendorAccountNumber": "DYNF-V004", "VendorName": "Cintas Corporation",        "VendorGroupId": "FACIL",   "CurrencyCode": "USD", "AnnualSpend": 72000.0,   "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V004"},
    {"VendorAccountNumber": "DYNF-V005", "VendorName": "ServiceNow Inc",            "VendorGroupId": "SOFTWR",  "CurrencyCode": "USD", "AnnualSpend": 245000.0,  "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V005"},
    {"VendorAccountNumber": "DYNF-V006", "VendorName": "Pricewaterhouse Coopers",   "VendorGroupId": "AUDIT",   "CurrencyCode": "USD", "AnnualSpend": 480000.0,  "PaymentTermBaseDays": 45, "InvoiceAccount": "DYNF-V006"},
    {"VendorAccountNumber": "DYNF-V007", "VendorName": "T-Mobile Business",         "VendorGroupId": "TELCOM",  "CurrencyCode": "USD", "AnnualSpend": 96000.0,   "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V007"},
    {"VendorAccountNumber": "DYNF-V008", "VendorName": "Iron Mountain Inc",         "VendorGroupId": "STOR",    "CurrencyCode": "USD", "AnnualSpend": 54000.0,   "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V008"},
    {"VendorAccountNumber": "DYNF-V009", "VendorName": "Salesforce Inc",            "VendorGroupId": "SOFTWR",  "CurrencyCode": "USD", "AnnualSpend": 312000.0,  "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V009"},
    {"VendorAccountNumber": "DYNF-V010", "VendorName": "Workday Inc",               "VendorGroupId": "SOFTWR",  "CurrencyCode": "USD", "AnnualSpend": 168000.0,  "PaymentTermBaseDays": 30, "InvoiceAccount": "DYNF-V010"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
}


class DynamicsFinanceMockConnector(ConnectorBase):
    """Mock Microsoft Dynamics 365 Finance connector."""

    CONNECTOR_ID = "dynamics_finance"
    DISPLAY_NAME = "Microsoft Dynamics 365 Finance"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Dynamics Finance Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["VendorAccountNumber", "VendorName", "VendorGroupId", "CurrencyCode", "AnnualSpend", "PaymentTermBaseDays", "InvoiceAccount"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Dynamics Finance connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["VendorAccountNumber"],
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
                    source_id=raw["VendorAccountNumber"],
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
            latency_ms=88.0,
        )
