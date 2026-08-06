"""
scout/connectors/mock/coupa.py — Mock Coupa Procurement connector.

Coupa is a leading spend management and procurement platform.
Entity types: supplier
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

_MOCK_SUPPLIERS = [
    {"id": "cup-s001", "name": "Cisco Systems Inc",       "number": "SUP-1001", "status": "active",   "supplier_type": "Strategic",   "payment_term": {"code": "NET30"},  "primary_contact": {"email": "enterprise@cisco.com"},       "total_invoiced_amount": 1250000.0, "contract_expiry_date": "2025-06-30"},
    {"id": "cup-s002", "name": "Microsoft Corporation",   "number": "SUP-1002", "status": "active",   "supplier_type": "Strategic",   "payment_term": {"code": "NET30"},  "primary_contact": {"email": "enterprise@microsoft.com"},   "total_invoiced_amount": 980000.0,  "contract_expiry_date": "2025-01-31"},
    {"id": "cup-s003", "name": "Crowdstrike Holdings",    "number": "SUP-1003", "status": "active",   "supplier_type": "Preferred",   "payment_term": {"code": "NET30"},  "primary_contact": {"email": "billing@crowdstrike.com"},    "total_invoiced_amount": 420000.0,  "contract_expiry_date": "2024-09-30"},
    {"id": "cup-s004", "name": "Deloitte Consulting LLP", "number": "SUP-1004", "status": "active",   "supplier_type": "Strategic",   "payment_term": {"code": "NET45"},  "primary_contact": {"email": "billing@deloitte.com"},       "total_invoiced_amount": 1850000.0, "contract_expiry_date": None},
    {"id": "cup-s005", "name": "Snowflake Inc",           "number": "SUP-1005", "status": "active",   "supplier_type": "Preferred",   "payment_term": {"code": "NET30"},  "primary_contact": {"email": "enterprise@snowflake.com"},   "total_invoiced_amount": 380000.0,  "contract_expiry_date": "2024-12-31"},
    {"id": "cup-s006", "name": "Johnson Controls Intl",  "number": "SUP-1006", "status": "active",   "supplier_type": "Approved",    "payment_term": {"code": "NET30"},  "primary_contact": {"email": "accounts@johnsoncontrols.com"},"total_invoiced_amount": 175000.0,  "contract_expiry_date": "2025-03-31"},
    {"id": "cup-s007", "name": "Palo Alto Networks Inc",  "number": "SUP-1007", "status": "active",   "supplier_type": "Preferred",   "payment_term": {"code": "NET30"},  "primary_contact": {"email": "billing@paloaltonetworks.com"},"total_invoiced_amount": 510000.0,  "contract_expiry_date": "2024-11-30"},
    {"id": "cup-s008", "name": "Ricoh USA Inc",           "number": "SUP-1008", "status": "active",   "supplier_type": "Approved",    "payment_term": {"code": "NET30"},  "primary_contact": {"email": "billing@ricoh-usa.com"},      "total_invoiced_amount": 88000.0,   "contract_expiry_date": "2024-08-31"},
    {"id": "cup-s009", "name": "ZScaler Inc",             "number": "SUP-1009", "status": "active",   "supplier_type": "Preferred",   "payment_term": {"code": "NET30"},  "primary_contact": {"email": "billing@zscaler.com"},        "total_invoiced_amount": 265000.0,  "contract_expiry_date": "2025-02-28"},
    {"id": "cup-s010", "name": "Sievert Office Supply",   "number": "SUP-1010", "status": "inactive", "supplier_type": "One-Time",    "payment_term": {"code": "NET15"},  "primary_contact": {"email": "ar@sievert.com"},             "total_invoiced_amount": 12000.0,   "contract_expiry_date": None},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "supplier": _MOCK_SUPPLIERS,
}


class CoupaMockConnector(ConnectorBase):
    """Mock Coupa Procurement connector."""

    CONNECTOR_ID = "coupa"
    DISPLAY_NAME = "Coupa"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="supplier",
                display_name="Coupa Suppliers",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_SUPPLIERS),
                fields=["id", "name", "number", "status", "supplier_type", "payment_term", "primary_contact", "total_invoiced_amount", "contract_expiry_date"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Coupa connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            primary_contact = raw.get("primary_contact", {})
            email = primary_contact.get("email") if isinstance(primary_contact, dict) else None
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
            checkpoint={"updated_at": datetime.utcnow().isoformat()},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=65.0,
        )
