"""
scout/connectors/mock/sap.py — Mock SAP S/4HANA ERP connector.

SAP S/4HANA for enterprise resource planning — vendors and employees.
Entity types: vendor, employee
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
    {"VendorId": "SAP-V100", "VendorName": "Siemens AG",                "AccountGroup": "LIEF", "PaymentTerms": "ZB30", "AnnualSpend": 1850000.0, "PurchasingOrg": "1000"},
    {"VendorId": "SAP-V101", "VendorName": "SAP SE",                    "AccountGroup": "LIEF", "PaymentTerms": "NT30", "AnnualSpend": 420000.0,  "PurchasingOrg": "1000"},
    {"VendorId": "SAP-V102", "VendorName": "Deutsche Telekom AG",       "AccountGroup": "DIEN", "PaymentTerms": "NT30", "AnnualSpend": 185000.0,  "PurchasingOrg": "1000"},
    {"VendorId": "SAP-V103", "VendorName": "KPMG AG",                   "AccountGroup": "BERA", "PaymentTerms": "NT45", "AnnualSpend": 580000.0,  "PurchasingOrg": "1000"},
    {"VendorId": "SAP-V104", "VendorName": "Bosch GmbH",                "AccountGroup": "LIEF", "PaymentTerms": "ZB14", "AnnualSpend": 2100000.0, "PurchasingOrg": "2000"},
    {"VendorId": "SAP-V105", "VendorName": "DHL Supply Chain GmbH",     "AccountGroup": "DIEN", "PaymentTerms": "NT30", "AnnualSpend": 340000.0,  "PurchasingOrg": "2000"},
    {"VendorId": "SAP-V106", "VendorName": "Accenture GmbH",            "AccountGroup": "BERA", "PaymentTerms": "NT30", "AnnualSpend": 760000.0,  "PurchasingOrg": "1000"},
    {"VendorId": "SAP-V107", "VendorName": "Microsoft Deutschland GmbH","AccountGroup": "SOFT", "PaymentTerms": "NT30", "AnnualSpend": 295000.0,  "PurchasingOrg": "1000"},
]

_MOCK_EMPLOYEES = [
    {"EmployeeId": "SAP-E001", "FirstName": "Hans",     "LastName": "Müller",      "Email": "h.mueller@globalcorp-de.com",   "Position": "Vorstand Finanzen (CFO)",         "OrganizationalUnit": "Finance",      "ManagerId": None,        "ContractType": "Permanent"},
    {"EmployeeId": "SAP-E002", "FirstName": "Katrin",   "LastName": "Schneider",   "Email": "k.schneider@globalcorp-de.com", "Position": "Leiter Controlling",              "OrganizationalUnit": "Controlling",  "ManagerId": "SAP-E001",  "ContractType": "Permanent"},
    {"EmployeeId": "SAP-E003", "FirstName": "Thomas",   "LastName": "Weber",       "Email": "t.weber@globalcorp-de.com",     "Position": "Einkaufsleiter (VP Procurement)", "OrganizationalUnit": "Procurement",  "ManagerId": None,        "ContractType": "Permanent"},
    {"EmployeeId": "SAP-E004", "FirstName": "Andrea",   "LastName": "Fischer",     "Email": "a.fischer@globalcorp-de.com",   "Position": "Procurement Manager",             "OrganizationalUnit": "Procurement",  "ManagerId": "SAP-E003",  "ContractType": "Permanent"},
    {"EmployeeId": "SAP-E005", "FirstName": "Stefan",   "LastName": "Braun",       "Email": "s.braun@globalcorp-de.com",     "Position": "Senior Buyer",                    "OrganizationalUnit": "Procurement",  "ManagerId": "SAP-E004",  "ContractType": "Permanent"},
    {"EmployeeId": "SAP-E006", "FirstName": "Monika",   "LastName": "Zimmermann",  "Email": "m.zimmermann@globalcorp-de.com","Position": "SAP Basis Administrator",         "OrganizationalUnit": "IT",           "ManagerId": None,        "ContractType": "Permanent"},
    {"EmployeeId": "SAP-E007", "FirstName": "Klaus",    "LastName": "Hoffmann",    "Email": "k.hoffmann@globalcorp-de.com",  "Position": "ABAP Developer",                  "OrganizationalUnit": "IT",           "ManagerId": "SAP-E006",  "ContractType": "Contractor"},
    {"EmployeeId": "SAP-E008", "FirstName": "Ursula",   "LastName": "Koch",        "Email": "u.koch@globalcorp-de.com",      "Position": "HR Director",                     "OrganizationalUnit": "HR",           "ManagerId": None,        "ContractType": "Permanent"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
    "employee": _MOCK_EMPLOYEES,
}


class SAPMockConnector(ConnectorBase):
    """Mock SAP S/4HANA ERP connector."""

    CONNECTOR_ID = "sap"
    DISPLAY_NAME = "SAP S/4HANA"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="SAP Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["VendorId", "VendorName", "AccountGroup", "PaymentTerms", "AnnualSpend", "PurchasingOrg"],
            ),
            EntitySchema(
                entity_type="employee",
                display_name="SAP Employees",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_EMPLOYEES),
                fields=["EmployeeId", "FirstName", "LastName", "Email", "Position", "OrganizationalUnit", "ManagerId", "ContractType"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"SAP connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            if entity_type == "vendor":
                source_id = raw["VendorId"]
                name = raw.get("VendorName")
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=name,
                )
            else:
                source_id = raw["EmployeeId"]
                email = raw.get("Email")
                name = f"{raw.get('FirstName', '')} {raw.get('LastName', '')}".strip()
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=email,
                    name_hint=name,
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
                if entity_type == "vendor":
                    source_id = raw["VendorId"]
                    yield RawRecord(
                        connector_id=self.CONNECTOR_ID,
                        entity_type=entity_type,
                        source_id=source_id,
                        tenant_id=self.tenant_id,
                        payload=raw,
                        name_hint=raw.get("VendorName"),
                    )
                else:
                    source_id = raw["EmployeeId"]
                    yield RawRecord(
                        connector_id=self.CONNECTOR_ID,
                        entity_type=entity_type,
                        source_id=source_id,
                        tenant_id=self.tenant_id,
                        payload=raw,
                        email_hint=raw.get("Email"),
                        name_hint=f"{raw.get('FirstName', '')} {raw.get('LastName', '')}".strip(),
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
            latency_ms=182.0,
        )
