"""
scout/connectors/mock/quickbooks.py — Mock QuickBooks Online ERP connector.

QuickBooks Online for small/mid-market accounting.
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
    {"Id": "qb-v001", "DisplayName": "Adobe Systems Inc",         "CompanyName": "Adobe Systems Inc",         "PrimaryEmailAddr": {"Address": "billing@adobe.com"},         "Balance": 4200.0,   "vendor_type": "Software"},
    {"Id": "qb-v002", "DisplayName": "Google Workspace",          "CompanyName": "Google LLC",                "PrimaryEmailAddr": {"Address": "billing@google.com"},         "Balance": 1850.0,   "vendor_type": "Software"},
    {"Id": "qb-v003", "DisplayName": "Stripe Inc",                "CompanyName": "Stripe Inc",                "PrimaryEmailAddr": {"Address": "billing@stripe.com"},         "Balance": 0.0,      "vendor_type": "Payment Processing"},
    {"Id": "qb-v004", "DisplayName": "Gusto Payroll",             "CompanyName": "Gusto Inc",                 "PrimaryEmailAddr": {"Address": "billing@gusto.com"},          "Balance": 18500.0,  "vendor_type": "HR Software"},
    {"Id": "qb-v005", "DisplayName": "Quickbase LLC",             "CompanyName": "Quickbase LLC",             "PrimaryEmailAddr": {"Address": "ar@quickbase.com"},           "Balance": 2400.0,   "vendor_type": "Software"},
    {"Id": "qb-v006", "DisplayName": "Comcast Business",          "CompanyName": "Comcast Business",          "PrimaryEmailAddr": {"Address": "businessbilling@comcast.com"},"Balance": 890.0,    "vendor_type": "Telecom"},
    {"Id": "qb-v007", "DisplayName": "WeWork Inc",                "CompanyName": "WeWork Companies Inc",      "PrimaryEmailAddr": {"Address": "enterprise@wework.com"},      "Balance": 14200.0,  "vendor_type": "Office Space"},
    {"Id": "qb-v008", "DisplayName": "FedEx Corporation",         "CompanyName": "FedEx Corporation",         "PrimaryEmailAddr": {"Address": "billing@fedex.com"},          "Balance": 3100.0,   "vendor_type": "Shipping"},
    {"Id": "qb-v009", "DisplayName": "Intuit QuickBooks",         "CompanyName": "Intuit Inc",                "PrimaryEmailAddr": {"Address": "billing@intuit.com"},         "Balance": 600.0,    "vendor_type": "Software"},
    {"Id": "qb-v010", "DisplayName": "Verizon Business",          "CompanyName": "Verizon Communications",    "PrimaryEmailAddr": {"Address": "businessaccounts@verizon.com"},"Balance": 1250.0,   "vendor_type": "Telecom"},
]

# Compute annual spend from balance * 12 (for mock purposes) using realistic values
_ANNUAL_SPEND_MAP = {
    "qb-v001": 50400.0,   # Adobe
    "qb-v002": 22200.0,   # Google Workspace
    "qb-v003": 85000.0,   # Stripe (payment processing fees)
    "qb-v004": 222000.0,  # Gusto payroll
    "qb-v005": 28800.0,   # Quickbase
    "qb-v006": 10680.0,   # Comcast
    "qb-v007": 170400.0,  # WeWork
    "qb-v008": 37200.0,   # FedEx
    "qb-v009": 7200.0,    # Intuit
    "qb-v010": 15000.0,   # Verizon
}

for v in _MOCK_VENDORS:
    v["annual_spend"] = _ANNUAL_SPEND_MAP.get(v["Id"], 12000.0)

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
}


class QuickBooksMockConnector(ConnectorBase):
    """Mock QuickBooks Online ERP connector."""

    CONNECTOR_ID = "quickbooks"
    DISPLAY_NAME = "QuickBooks Online"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="QuickBooks Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["Id", "DisplayName", "CompanyName", "PrimaryEmailAddr", "Balance", "vendor_type", "annual_spend"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"QuickBooks connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            email_addr = raw.get("PrimaryEmailAddr", {})
            email = email_addr.get("Address") if isinstance(email_addr, dict) else None
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["Id"],
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=raw.get("DisplayName"),
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
                    source_id=raw["Id"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=raw.get("DisplayName"),
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
            latency_ms=61.0,
        )
