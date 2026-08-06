"""
scout/connectors/mock/concur.py — Mock SAP Concur expense management connector.

SAP Concur is the leading enterprise travel and expense management platform.
Entity types: vendor, expense_report
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
    {"VendorCode": "CCR-V001", "VendorName": "American Airlines",    "VendorType": "Airline",         "City": "Fort Worth",    "AnnualSpend": 285000.0},
    {"VendorCode": "CCR-V002", "VendorName": "Hilton Hotels",        "VendorType": "Hotel",           "City": "McLean",        "AnnualSpend": 198000.0},
    {"VendorCode": "CCR-V003", "VendorName": "Hertz Car Rental",     "VendorType": "Car Rental",      "City": "Estero",        "AnnualSpend": 87000.0},
    {"VendorCode": "CCR-V004", "VendorName": "Lyft Business",        "VendorType": "Ground Transport","City": "San Francisco", "AnnualSpend": 54000.0},
    {"VendorCode": "CCR-V005", "VendorName": "Starbucks",            "VendorType": "Meals",           "City": "Seattle",       "AnnualSpend": 32000.0},
    {"VendorCode": "CCR-V006", "VendorName": "Southwest Airlines",   "VendorType": "Airline",         "City": "Dallas",        "AnnualSpend": 142000.0},
    {"VendorCode": "CCR-V007", "VendorName": "Hyatt Hotels",         "VendorType": "Hotel",           "City": "Chicago",       "AnnualSpend": 115000.0},
]

_MOCK_EXPENSE_REPORTS = [
    {"ReportId": "RPT-2024-001", "EmployeeId": "EMP-010", "EmployeeName": "Marcus Johnson",   "Total": 2847.50, "SubmitDate": "2024-01-08", "ApprovalStatus": "Approved"},
    {"ReportId": "RPT-2024-002", "EmployeeId": "EMP-011", "EmployeeName": "Priya Patel",      "Total": 1924.00, "SubmitDate": "2024-01-10", "ApprovalStatus": "Approved"},
    {"ReportId": "RPT-2024-003", "EmployeeId": "EMP-001", "EmployeeName": "Sarah Chen",       "Total": 4512.25, "SubmitDate": "2024-01-12", "ApprovalStatus": "Pending"},
    {"ReportId": "RPT-2024-004", "EmployeeId": "EMP-020", "EmployeeName": "Elena Vasquez",    "Total": 892.00,  "SubmitDate": "2024-01-09", "ApprovalStatus": "Approved"},
    {"ReportId": "RPT-2024-005", "EmployeeId": "EMP-021", "EmployeeName": "James Liu",        "Total": 1105.75, "SubmitDate": "2024-01-11", "ApprovalStatus": "Pending"},
    {"ReportId": "RPT-2024-006", "EmployeeId": "EMP-003", "EmployeeName": "Amanda Foster",    "Total": 6820.00, "SubmitDate": "2024-01-07", "ApprovalStatus": "Approved"},
    {"ReportId": "RPT-2024-007", "EmployeeId": "EMP-030", "EmployeeName": "Lisa Nakamura",    "Total": 445.50,  "SubmitDate": "2024-01-14", "ApprovalStatus": "Submitted"},
    {"ReportId": "RPT-2024-008", "EmployeeId": "EMP-012", "EmployeeName": "David Kim",        "Total": 1688.25, "SubmitDate": "2024-01-13", "ApprovalStatus": "Rejected"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
    "expense_report": _MOCK_EXPENSE_REPORTS,
}


class ConcurMockConnector(ConnectorBase):
    """Mock SAP Concur expense management connector."""

    CONNECTOR_ID = "concur"
    DISPLAY_NAME = "SAP Concur"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Concur Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["VendorCode", "VendorName", "VendorType", "City", "AnnualSpend"],
            ),
            EntitySchema(
                entity_type="expense_report",
                display_name="Concur Expense Reports",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_EXPENSE_REPORTS),
                fields=["ReportId", "EmployeeId", "EmployeeName", "Total", "SubmitDate", "ApprovalStatus"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Concur connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            source_id = raw.get("VendorCode") or raw.get("ReportId", "")
            name = raw.get("VendorName") or raw.get("EmployeeName", "")
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=source_id,
                tenant_id=self.tenant_id,
                payload=raw,
                name_hint=name,
            )

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        all_records = list(_ENTITY_DATA.get(entity_type, []))
        changed = [r for r in all_records if random.random() < 0.20]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                source_id = raw.get("VendorCode") or raw.get("ReportId", "")
                name = raw.get("VendorName") or raw.get("EmployeeName", "")
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=name,
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"modifiedDateBefore": datetime.utcnow().isoformat()},
        )
        return _generate(), updated_cursor

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.CONNECTOR_ID,
            is_healthy=True,
            latency_ms=71.0,
        )
