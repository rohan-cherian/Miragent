"""
scout/connectors/mock/epicor.py — Mock Epicor ERP connector.

Epicor is an ERP platform popular in manufacturing and distribution.
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
    {"VendorNum": 5001, "Name": "Parker Hannifin Corp",       "VendorType": "MANUF",   "CurrencyCode": "USD", "TermsCode": "NET30", "AnnualSpend": 1240000.0},
    {"VendorNum": 5002, "Name": "Grainger Industrial Supply", "VendorType": "DIST",    "CurrencyCode": "USD", "TermsCode": "NET30", "AnnualSpend": 380000.0},
    {"VendorNum": 5003, "Name": "Rockwell Automation Inc",    "VendorType": "MANUF",   "CurrencyCode": "USD", "TermsCode": "NET45", "AnnualSpend": 875000.0},
    {"VendorNum": 5004, "Name": "MSC Industrial Direct Co",   "VendorType": "DIST",    "CurrencyCode": "USD", "TermsCode": "NET30", "AnnualSpend": 215000.0},
    {"VendorNum": 5005, "Name": "Hexion Inc",                 "VendorType": "CHEM",    "CurrencyCode": "USD", "TermsCode": "NET45", "AnnualSpend": 560000.0},
    {"VendorNum": 5006, "Name": "UPS Supply Chain Solutions", "VendorType": "LOGIST",  "CurrencyCode": "USD", "TermsCode": "NET30", "AnnualSpend": 320000.0},
    {"VendorNum": 5007, "Name": "Emerson Electric Co",        "VendorType": "MANUF",   "CurrencyCode": "USD", "TermsCode": "NET45", "AnnualSpend": 695000.0},
    {"VendorNum": 5008, "Name": "Fastenal Company",           "VendorType": "DIST",    "CurrencyCode": "USD", "TermsCode": "NET30", "AnnualSpend": 145000.0},
]

_MOCK_EMPLOYEES = [
    {"EmpID": "EPC-E001", "FirstName": "Gerald",   "LastName": "Kowalski",    "Email": "g.kowalski@lakeview-mfg.com",   "EmpRoleCode": "PLANTMGR", "DeptDescription": "Plant Operations", "SupervisorID": None},
    {"EmpID": "EPC-E002", "FirstName": "Sandra",   "LastName": "Ashworth",    "Email": "s.ashworth@lakeview-mfg.com",   "EmpRoleCode": "PRODSUP",  "DeptDescription": "Production",       "SupervisorID": "EPC-E001"},
    {"EmpID": "EPC-E003", "FirstName": "Mikhail",  "LastName": "Sorokin",     "Email": "m.sorokin@lakeview-mfg.com",    "EmpRoleCode": "ENGRSR",   "DeptDescription": "Engineering",      "SupervisorID": "EPC-E001"},
    {"EmpID": "EPC-E004", "FirstName": "Dianne",   "LastName": "Shepherd",    "Email": "d.shepherd@lakeview-mfg.com",   "EmpRoleCode": "QCMGR",    "DeptDescription": "Quality Control",  "SupervisorID": "EPC-E001"},
    {"EmpID": "EPC-E005", "FirstName": "Earl",     "LastName": "Tompkins",    "Email": "e.tompkins@lakeview-mfg.com",   "EmpRoleCode": "PURCHSR",  "DeptDescription": "Purchasing",       "SupervisorID": None},
    {"EmpID": "EPC-E006", "FirstName": "Lourdes",  "LastName": "Navarro",     "Email": "l.navarro@lakeview-mfg.com",    "EmpRoleCode": "BUYER",    "DeptDescription": "Purchasing",       "SupervisorID": "EPC-E005"},
    {"EmpID": "EPC-E007", "FirstName": "Cecil",    "LastName": "Drummond",    "Email": "c.drummond@lakeview-mfg.com",   "EmpRoleCode": "ACCTMGR",  "DeptDescription": "Accounting",       "SupervisorID": None},
    {"EmpID": "EPC-E008", "FirstName": "Renata",   "LastName": "Weiss",       "Email": "r.weiss@lakeview-mfg.com",      "EmpRoleCode": "ACCT",     "DeptDescription": "Accounting",       "SupervisorID": "EPC-E007"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "vendor": _MOCK_VENDORS,
    "employee": _MOCK_EMPLOYEES,
}


class EpicorMockConnector(ConnectorBase):
    """Mock Epicor ERP connector."""

    CONNECTOR_ID = "epicor"
    DISPLAY_NAME = "Epicor ERP"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Epicor Vendors",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_VENDORS),
                fields=["VendorNum", "Name", "VendorType", "CurrencyCode", "TermsCode", "AnnualSpend"],
            ),
            EntitySchema(
                entity_type="employee",
                display_name="Epicor Employees",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_EMPLOYEES),
                fields=["EmpID", "FirstName", "LastName", "Email", "EmpRoleCode", "DeptDescription", "SupervisorID"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Epicor connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            if entity_type == "vendor":
                source_id = str(raw["VendorNum"])
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    name_hint=raw.get("Name"),
                )
            else:
                source_id = raw["EmpID"]
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=raw.get("Email"),
                    name_hint=f"{raw.get('FirstName', '')} {raw.get('LastName', '')}".strip(),
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
                    source_id = str(raw["VendorNum"])
                    yield RawRecord(
                        connector_id=self.CONNECTOR_ID,
                        entity_type=entity_type,
                        source_id=source_id,
                        tenant_id=self.tenant_id,
                        payload=raw,
                        name_hint=raw.get("Name"),
                    )
                else:
                    source_id = raw["EmpID"]
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
            latency_ms=95.0,
        )
