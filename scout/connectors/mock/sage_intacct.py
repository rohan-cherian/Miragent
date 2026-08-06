"""
scout/connectors/mock/sage_intacct.py — Mock Sage Intacct ERP connector.

Sage Intacct is a cloud-native ERP popular in mid-market companies.
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
    {"VENDORID": "SI-V001", "NAME": "Zuora Inc",                  "VENDTYPE": "Software",            "ONETIME": "false", "STATUS": "active",   "TOTALDUE": 0.0,      "ANNUALSPEND": 142000.0, "PAYMENTPRIORITY": "Normal"},
    {"VENDORID": "SI-V002", "NAME": "HubSpot Inc",                "VENDTYPE": "Software",            "ONETIME": "false", "STATUS": "active",   "TOTALDUE": 11750.0,  "ANNUALSPEND": 141000.0, "PAYMENTPRIORITY": "Normal"},
    {"VENDORID": "SI-V003", "NAME": "Dun & Bradstreet Corp",      "VENDTYPE": "Data Services",       "ONETIME": "false", "STATUS": "active",   "TOTALDUE": 0.0,      "ANNUALSPEND": 38400.0,  "PAYMENTPRIORITY": "Normal"},
    {"VENDORID": "SI-V004", "NAME": "Ernst & Young LLP",          "VENDTYPE": "Professional Services","ONETIME": "false", "STATUS": "active",   "TOTALDUE": 95000.0,  "ANNUALSPEND": 540000.0, "PAYMENTPRIORITY": "High"},
    {"VENDORID": "SI-V005", "NAME": "Twilio Inc",                 "VENDTYPE": "Software",            "ONETIME": "false", "STATUS": "active",   "TOTALDUE": 4200.0,   "ANNUALSPEND": 62000.0,  "PAYMENTPRIORITY": "Normal"},
    {"VENDORID": "SI-V006", "NAME": "Rackspace Technology Inc",   "VENDTYPE": "Cloud Infrastructure","ONETIME": "false", "STATUS": "active",   "TOTALDUE": 18500.0,  "ANNUALSPEND": 228000.0, "PAYMENTPRIORITY": "High"},
    {"VENDORID": "SI-V007", "NAME": "Datadog Inc",                "VENDTYPE": "Software",            "ONETIME": "false", "STATUS": "active",   "TOTALDUE": 0.0,      "ANNUALSPEND": 85000.0,  "PAYMENTPRIORITY": "Normal"},
    {"VENDORID": "SI-V008", "NAME": "Glassdoor Inc",              "VENDTYPE": "Recruiting",          "ONETIME": "false", "STATUS": "inactive", "TOTALDUE": 0.0,      "ANNUALSPEND": 18000.0,  "PAYMENTPRIORITY": "Low"},
    {"VENDORID": "SI-V009", "NAME": "Sprinklr Inc",               "VENDTYPE": "Software",            "ONETIME": "false", "STATUS": "active",   "TOTALDUE": 7800.0,   "ANNUALSPEND": 96000.0,  "PAYMENTPRIORITY": "Normal"},
    {"VENDORID": "SI-V010", "NAME": "Carta Inc",                  "VENDTYPE": "Legal & Compliance",  "ONETIME": "false", "STATUS": "active",   "TOTALDUE": 0.0,      "ANNUALSPEND": 24000.0,  "PAYMENTPRIORITY": "Normal"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
}


class SageIntacctMockConnector(ConnectorBase):
    """Mock Sage Intacct ERP connector."""

    CONNECTOR_ID = "sage_intacct"
    DISPLAY_NAME = "Sage Intacct"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Sage Intacct Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["VENDORID", "NAME", "VENDTYPE", "ONETIME", "STATUS", "TOTALDUE", "ANNUALSPEND", "PAYMENTPRIORITY"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Sage Intacct connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=raw["VENDORID"],
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=raw.get("NAME"),
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
                    source_id=raw["VENDORID"],
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=raw.get("NAME"),
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
            latency_ms=74.0,
        )
