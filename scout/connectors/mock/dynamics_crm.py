"""
scout/connectors/mock/dynamics_crm.py — Mock Microsoft Dynamics 365 CRM connector.

Dynamics CRM for contacts and accounts.
Entity types: contact, account
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

_MOCK_CONTACTS = [
    {"contactid": "dyn-ct001", "fullname": "Margaret Holbrook",   "emailaddress1": "m.holbrook@ironbridge-mfg.com",   "jobtitle": "Chief Procurement Officer",     "departmentname": "Procurement",  "_parentcustomerid_value": "dyn-ac001", "statecode": 0},
    {"contactid": "dyn-ct002", "fullname": "Elijah Thornton",      "emailaddress1": "e.thornton@ironbridge-mfg.com",   "jobtitle": "Senior Buyer",                  "departmentname": "Procurement",  "_parentcustomerid_value": "dyn-ac001", "statecode": 0},
    {"contactid": "dyn-ct003", "fullname": "Sylvia Nakagawa",      "emailaddress1": "s.nakagawa@coastal-energy.com",   "jobtitle": "VP of Operations",              "departmentname": "Operations",   "_parentcustomerid_value": "dyn-ac002", "statecode": 0},
    {"contactid": "dyn-ct004", "fullname": "Anthony Deluca",       "emailaddress1": "a.deluca@coastal-energy.com",     "jobtitle": "Operations Manager",            "departmentname": "Operations",   "_parentcustomerid_value": "dyn-ac002", "statecode": 0},
    {"contactid": "dyn-ct005", "fullname": "Priya Venkataraman",   "emailaddress1": "p.venkataraman@bluehorizon-re.com","jobtitle": "Chief Financial Officer",      "departmentname": "Finance",      "_parentcustomerid_value": "dyn-ac003", "statecode": 0},
    {"contactid": "dyn-ct006", "fullname": "Samuel Griffiths",     "emailaddress1": "s.griffiths@bluehorizon-re.com",  "jobtitle": "Financial Controller",          "departmentname": "Finance",      "_parentcustomerid_value": "dyn-ac003", "statecode": 0},
    {"contactid": "dyn-ct007", "fullname": "Camille Dupont",       "emailaddress1": "c.dupont@grandview-hotel.com",    "jobtitle": "Director of Revenue",           "departmentname": "Revenue",      "_parentcustomerid_value": "dyn-ac004", "statecode": 0},
    {"contactid": "dyn-ct008", "fullname": "Julian Hartmann",      "emailaddress1": "j.hartmann@tempest-tech.com",     "jobtitle": "Chief Executive Officer",       "departmentname": "Executive",    "_parentcustomerid_value": "dyn-ac005", "statecode": 1},
]

_MOCK_ACCOUNTS = [
    {"accountid": "dyn-ac001", "name": "Ironbridge Manufacturing",   "industrycode": 3,  "revenue": 145000000.0, "numberofemployees": 890,  "ownerid": "dyn-ct001", "accounttype": "Customer"},
    {"accountid": "dyn-ac002", "name": "Coastal Energy Partners",    "industrycode": 7,  "revenue": 380000000.0, "numberofemployees": 2200, "ownerid": "dyn-ct003", "accounttype": "Customer"},
    {"accountid": "dyn-ac003", "name": "Blue Horizon Real Estate",   "industrycode": 12, "revenue": 92000000.0,  "numberofemployees": 310,  "ownerid": "dyn-ct005", "accounttype": "Prospect"},
    {"accountid": "dyn-ac004", "name": "Grandview Hotel Group",      "industrycode": 9,  "revenue": 61000000.0,  "numberofemployees": 480,  "ownerid": "dyn-ct007", "accounttype": "Prospect"},
    {"accountid": "dyn-ac005", "name": "Tempest Technologies Inc",   "industrycode": 1,  "revenue": 58000000.0,  "numberofemployees": 340,  "ownerid": "dyn-ct008", "accounttype": "Former Customer"},
]

_ENTITY_DATA: dict[str, list[dict]] = {
    "contact": _MOCK_CONTACTS,
    "account": _MOCK_ACCOUNTS,
}


class DynamicsCRMMockConnector(ConnectorBase):
    """Mock Microsoft Dynamics 365 CRM connector."""

    CONNECTOR_ID = "dynamics_crm"
    DISPLAY_NAME = "Microsoft Dynamics 365 CRM"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 5.0

    def authenticate(self) -> bool:
        return True

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="contact",
                display_name="Dynamics CRM Contacts",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_CONTACTS),
                fields=["contactid", "fullname", "emailaddress1", "jobtitle", "departmentname", "_parentcustomerid_value", "statecode"],
            ),
            EntitySchema(
                entity_type="account",
                display_name="Dynamics CRM Accounts",
                supports_incremental=True,
                estimated_record_count=len(_MOCK_ACCOUNTS),
                fields=["accountid", "name", "industrycode", "revenue", "numberofemployees", "ownerid", "accounttype"],
            ),
        ]

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type not in _ENTITY_DATA:
            raise ValueError(f"Dynamics CRM connector does not support entity type: {entity_type}")

        for raw in _ENTITY_DATA[entity_type]:
            source_id = raw.get("contactid") or raw.get("accountid", "")
            email = raw.get("emailaddress1")
            name = raw.get("fullname") or raw.get("name", "")
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
        changed = [r for r in all_records if random.random() < 0.20]

        def _generate() -> Iterator[RawRecord]:
            for raw in changed:
                source_id = raw.get("contactid") or raw.get("accountid", "")
                email = raw.get("emailaddress1")
                name = raw.get("fullname") or raw.get("name", "")
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=source_id,
                    tenant_id=self.tenant_id,
                    payload=raw,
                    email_hint=email,
                    name_hint=name,
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
            latency_ms=55.0,
        )
