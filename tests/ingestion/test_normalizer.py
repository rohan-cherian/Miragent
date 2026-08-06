"""Tests for the normalizer — field mapping from raw records to canonical dicts."""

from datetime import datetime
import pytest

from scout.connectors.models import RawRecord
from scout.ingestion.normalizer import normalize, _clean_email


def make_record(connector_id: str, entity_type: str, source_id: str, payload: dict) -> RawRecord:
    return RawRecord(
        connector_id=connector_id,
        entity_type=entity_type,
        source_id=source_id,
        tenant_id="test-tenant",
        payload=payload,
    )


class TestSalesforceNormalizer:

    def test_user_maps_to_person(self):
        record = make_record("salesforce", "user", "005abc", {
            "Id": "005abc", "Name": "Sarah Chen", "Email": "S.CHEN@ACMECORP.COM",
            "Title": "VP of Sales", "Department": "Sales", "IsActive": True,
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "person"
        assert result["full_name"] == "Sarah Chen"
        assert result["email"] == "s.chen@acmecorp.com"  # lowercased
        assert result["job_title"] == "VP of Sales"
        assert result["is_active"] is True
        assert result["_source_connector"] == "salesforce"

    def test_user_email_is_lowercased(self):
        record = make_record("salesforce", "user", "001", {"Email": "User@COMPANY.COM", "Name": "X", "Id": "001"})
        result = normalize(record)
        assert result["email"] == "user@company.com"

    def test_account_maps_correctly(self):
        record = make_record("salesforce", "account", "001xyz", {
            "Id": "001xyz", "Name": "Pinnacle Partners",
            "Industry": "Financial Services", "AnnualRevenue": 45000000,
            "NumberOfEmployees": 320, "Type": "Customer", "OwnerId": "005abc",
        })
        result = normalize(record)
        assert result["entity_type"] == "account"
        assert result["name"] == "Pinnacle Partners"
        assert result["annual_revenue"] == 45000000.0
        assert result["employee_count"] == 320
        assert result["owner_salesforce_id"] == "005abc"

    def test_unknown_entity_type_returns_none(self):
        record = make_record("salesforce", "lead", "001", {"Id": "001"})
        result = normalize(record)
        assert result is None


class TestWorkdayNormalizer:

    def test_worker_maps_to_person(self):
        record = make_record("workday", "worker", "WD-0001", {
            "workerId": "WD-0001", "name": "Sarah Chen",
            "email": "s.chen@acmecorp.com", "employeeId": "EMP-001",
            "jobTitle": "VP of Sales", "department": "Sales",
            "managerId": "WD-0099", "employmentType": "Regular",
            "costCenter": "CC-100", "isActive": True, "startDate": "2021-03-15",
        })
        result = normalize(record)
        assert result["entity_type"] == "person"
        assert result["workday_id"] == "WD-0001"
        assert result["employee_id"] == "EMP-001"
        assert result["employment_type"] == "Regular"
        assert result["cost_center"] == "CC-100"
        assert result["manager_workday_id"] == "WD-0099"

    def test_contractor_employment_type_preserved(self):
        record = make_record("workday", "worker", "WD-0099", {
            "workerId": "WD-0099", "name": "Carlos M", "email": "c.m@acmecorp.com",
            "employmentType": "Contractor", "isActive": True,
        })
        result = normalize(record)
        assert result["employment_type"] == "Contractor"


class TestNetsuiteNormalizer:

    def test_vendor_maps_correctly(self):
        record = make_record("netsuite", "vendor", "V-001", {
            "internalId": "V-001", "entityId": "Salesforce Inc",
            "category": "Software", "annualSpend": 284000,
            "contractRenewal": "2024-09-30", "isActive": True,
            "paymentTerms": "Net 30", "primaryContact": "Enterprise Sales",
        })
        result = normalize(record)
        assert result["entity_type"] == "vendor"
        assert result["name"] == "Salesforce Inc"
        assert result["annual_spend"] == 284000.0
        assert result["contract_renewal"] == "2024-09-30"
        assert result["category"] == "Software"

    def test_vendor_normalized_name_is_lowercase(self):
        record = make_record("netsuite", "vendor", "V-002", {
            "internalId": "V-002", "entityId": "Amazon Web Services",
            "annualSpend": 890000,
        })
        result = normalize(record)
        assert " " not in result["normalized_name"]
        assert result["normalized_name"] == result["normalized_name"].lower()


class TestEmailHelper:

    def test_clean_email_lowercases(self):
        assert _clean_email("USER@COMPANY.COM") == "user@company.com"

    def test_clean_email_strips_whitespace(self):
        assert _clean_email("  user@company.com  ") == "user@company.com"

    def test_clean_email_none_for_empty(self):
        assert _clean_email("") is None
        assert _clean_email(None) is None

    def test_clean_email_none_for_no_at_sign(self):
        assert _clean_email("notanemail") is None


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 38 normalizers
# ─────────────────────────────────────────────────────────────────────────────

class TestDynamicsFinanceNormalizer:

    def test_vendor_maps_correctly(self):
        record = make_record("dynamics_finance", "vendor", "DYNF-V001", {
            "AccountNum": "DYNF-V001",
            "Name": "Capgemini US LLC",
            "VendorGroupId": "CONSULT",
            "CurrencyCode": "USD",
            "PaymentTermId": "Net30",
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "vendor"
        assert result["name"] == "Capgemini US LLC"
        assert result["category"] == "CONSULT"
        assert result["is_active"] is True

    def test_vendor_normalized_name_lowercase_no_spaces(self):
        record = make_record("dynamics_finance", "vendor", "V2", {
            "Name": "Oracle America Inc",
            "VendorGroupId": "SOFTWR",
        })
        result = normalize(record)
        assert result["normalized_name"] == result["normalized_name"].lower()
        assert " " not in result["normalized_name"]

    def test_vendor_payment_term_from_field(self):
        record = make_record("dynamics_finance", "vendor", "V3", {
            "Name": "Acme Corp",
            "PaymentTermId": "Net45",
        })
        result = normalize(record)
        assert result["payment_terms"] == "Net45"

    def test_worker_maps_to_person(self):
        record = make_record("dynamics_finance", "worker", "W001", {
            "PersonnelNumber": "W001",
            "PrimaryWorkerName": "Alice Smith",
            "PrimaryEmailAddress": "alice@acme.com",
            "WorkerType": "Employee",
            "OfficeLocation": "Chicago",
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "person"
        assert result["full_name"] == "Alice Smith"
        assert result["email"] == "alice@acme.com"
        assert result["employee_id"] == "W001"
        assert result["employment_type"] == "Regular"
        assert result["location"] == "Chicago"

    def test_worker_contractor_type(self):
        record = make_record("dynamics_finance", "worker", "W002", {
            "PersonnelNumber": "W002",
            "PrimaryWorkerName": "Bob Contractor",
            "PrimaryEmailAddress": "bob@acme.com",
            "WorkerType": "Contractor",
        })
        result = normalize(record)
        assert result["employment_type"] == "Contractor"

    def test_worker_name_fallback_to_personnel_number(self):
        record = make_record("dynamics_finance", "worker", "W003", {
            "PersonnelNumber": "W003",
            "PrimaryEmailAddress": "c@acme.com",
        })
        result = normalize(record)
        assert result["full_name"] == "W003"

    def test_unknown_entity_type_returns_none(self):
        record = make_record("dynamics_finance", "gl_entry", "GL001", {})
        result = normalize(record)
        assert result is None

    def test_provenance_tags(self):
        record = make_record("dynamics_finance", "worker", "W-PRV", {
            "PersonnelNumber": "W-PRV",
            "PrimaryEmailAddress": "prv@acme.com",
        })
        result = normalize(record)
        assert result["_source_connector"] == "dynamics_finance"
        assert result["_source_id"] == "W-PRV"


class TestAcumaticaNormalizer:

    def test_vendor_plain_fields(self):
        """Acumatica vendor without OData wrapping (mock data format)."""
        record = make_record("acumatica", "vendor", "ACU-V001", {
            "VendorID": "ACU-V001",
            "VendorName": "Avalara Inc",
            "VendorClass": "SOFTWARE",
            "Status": "Active",
            "AnnualSpend": 48000.0,
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "vendor"
        assert result["name"] == "Avalara Inc"
        assert result["category"] == "SOFTWARE"
        assert result["is_active"] is True
        assert result["annual_spend"] == 48000.0

    def test_vendor_odata_wrapped_fields(self):
        """Acumatica vendor with OData-wrapped fields."""
        record = make_record("acumatica", "vendor", "V-OD", {
            "VendorID": {"value": "V-OD", "type": "string"},
            "VendorName": {"value": "Box Inc", "type": "string"},
            "VendorClass": {"value": "SOFTWARE"},
            "Status": {"value": "Active"},
            "AnnualSpend": {"value": 36000.0},
        })
        result = normalize(record)
        assert result["name"] == "Box Inc"
        assert result["category"] == "SOFTWARE"
        assert result["is_active"] is True

    def test_vendor_inactive_status(self):
        record = make_record("acumatica", "vendor", "V-INA", {
            "VendorName": "Old Vendor",
            "Status": "Inactive",
        })
        result = normalize(record)
        assert result["is_active"] is False

    def test_employee_plain_fields(self):
        """Acumatica employee without OData wrapping."""
        record = make_record("acumatica", "employee", "E001", {
            "EmployeeID": "E001",
            "Status": "Active",
            "DepartmentID": "ENGINEERING",
            "PositionID": "SR_ENG",
            "ReportsToID": "MGR001",
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "person"
        assert result["employee_id"] == "E001"
        assert result["department"] == "ENGINEERING"
        assert result["job_title"] == "SR_ENG"
        assert result["is_active"] is True
        assert result["manager_source_id"] == "MGR001"

    def test_employee_odata_wrapped_fields(self):
        """Acumatica employee with OData-wrapped fields."""
        record = make_record("acumatica", "employee", "E-OD", {
            "EmployeeID": {"value": "E-OD"},
            "Status": {"value": "Active"},
            "DepartmentID": {"value": "FINANCE"},
            "PositionID": {"value": "ANALYST"},
            "ReportsToID": {"value": "DIRECTOR"},
        })
        result = normalize(record)
        assert result["employee_id"] == "E-OD"
        assert result["department"] == "FINANCE"
        assert result["job_title"] == "ANALYST"
        assert result["manager_source_id"] == "DIRECTOR"

    def test_employee_inactive_status_wrapped(self):
        record = make_record("acumatica", "employee", "E-OFF", {
            "EmployeeID": {"value": "E-OFF"},
            "Status": {"value": "Inactive"},
        })
        result = normalize(record)
        assert result["is_active"] is False

    def test_provenance_tags(self):
        record = make_record("acumatica", "vendor", "ACU-PRV", {
            "VendorName": "Test", "Status": "Active"
        })
        result = normalize(record)
        assert result["_source_connector"] == "acumatica"
        assert result["_source_id"] == "ACU-PRV"


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 39 normalizers — deferred entity types
# ─────────────────────────────────────────────────────────────────────────────

class TestRampTransactionNormalizer:

    def test_transaction_maps_correctly(self):
        record = make_record("ramp", "transaction", "rmp-t001", {
            "id": "rmp-t001",
            "merchant_id": "rmp-m001",
            "amount": 74500.0,
            "currency_code": "USD",
            "user_id": "rmp-usr001",
            "memo": "AWS - Monthly Usage Dec 2023",
            "date": "2024-01-01",
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "expense_transaction"
        assert result["transaction_id"] == "rmp-t001"
        assert result["merchant_id"] == "rmp-m001"
        assert result["amount"] == 74500.0
        assert result["currency_code"] == "USD"
        assert result["user_id"] == "rmp-usr001"
        assert result["memo"] == "AWS - Monthly Usage Dec 2023"
        assert result["transaction_date"] == "2024-01-01"
        assert result["source"] == "ramp"

    def test_transaction_amount_is_float(self):
        record = make_record("ramp", "transaction", "rmp-t002", {
            "id": "rmp-t002", "amount": "1240", "currency_code": "USD",
        })
        result = normalize(record)
        assert isinstance(result["amount"], float)
        assert result["amount"] == 1240.0

    def test_transaction_missing_fields_return_none(self):
        record = make_record("ramp", "transaction", "rmp-t003", {
            "id": "rmp-t003",
        })
        result = normalize(record)
        assert result is not None
        assert result["amount"] is None
        assert result["merchant_id"] is None
        assert result["user_id"] is None
        assert result["memo"] is None

    def test_transaction_default_currency(self):
        record = make_record("ramp", "transaction", "rmp-t004", {
            "id": "rmp-t004", "amount": 500.0,
        })
        result = normalize(record)
        assert result["currency_code"] == "USD"

    def test_provenance_tags(self):
        record = make_record("ramp", "transaction", "rmp-t001", {
            "id": "rmp-t001", "amount": 100.0,
        })
        result = normalize(record)
        assert result["_source_connector"] == "ramp"
        assert result["_source_id"] == "rmp-t001"


class TestConcurExpenseReportNormalizer:

    def test_expense_report_maps_correctly(self):
        record = make_record("concur", "expense_report", "RPT-2024-001", {
            "ReportId": "RPT-2024-001",
            "EmployeeId": "EMP-010",
            "EmployeeName": "Marcus Johnson",
            "Total": 2847.50,
            "SubmitDate": "2024-01-08",
            "ApprovalStatus": "Approved",
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "expense_report"
        assert result["report_id"] == "RPT-2024-001"
        assert result["employee_id"] == "EMP-010"
        assert result["employee_name"] == "Marcus Johnson"
        assert result["total_amount"] == 2847.50
        assert result["submit_date"] == "2024-01-08"
        assert result["approval_status"] == "Approved"
        assert result["source"] == "concur"

    def test_expense_report_pending_status(self):
        record = make_record("concur", "expense_report", "RPT-2024-003", {
            "ReportId": "RPT-2024-003",
            "EmployeeId": "EMP-001",
            "EmployeeName": "Sarah Chen",
            "Total": 4512.25,
            "SubmitDate": "2024-01-12",
            "ApprovalStatus": "Pending",
        })
        result = normalize(record)
        assert result["approval_status"] == "Pending"
        assert result["total_amount"] == 4512.25

    def test_expense_report_total_is_float(self):
        record = make_record("concur", "expense_report", "RPT-X", {
            "ReportId": "RPT-X", "Total": "1500",
        })
        result = normalize(record)
        assert isinstance(result["total_amount"], float)

    def test_expense_report_missing_fields_return_none(self):
        record = make_record("concur", "expense_report", "RPT-EMPTY", {
            "ReportId": "RPT-EMPTY",
        })
        result = normalize(record)
        assert result is not None
        assert result["employee_id"] is None
        assert result["employee_name"] is None
        assert result["total_amount"] is None

    def test_provenance_tags(self):
        record = make_record("concur", "expense_report", "RPT-PRV", {
            "ReportId": "RPT-PRV", "Total": 999.0,
        })
        result = normalize(record)
        assert result["_source_connector"] == "concur"
        assert result["_source_id"] == "RPT-PRV"


class TestServiceNowAssetNormalizer:

    def test_asset_maps_correctly(self):
        record = make_record("servicenow", "asset", "sn-a001", {
            "sys_id": "sn-a001",
            "name": "MacBook Pro 16 M3",
            "asset_tag": "ASSET-1001",
            "model_category": "Computer",
            "assigned_to": {"value": "sn-u004"},
            "cost": 3499.0,
            "install_status": "In use",
        })
        result = normalize(record)
        assert result is not None
        assert result["entity_type"] == "asset"
        assert result["asset_id"] == "sn-a001"
        assert result["name"] == "MacBook Pro 16 M3"
        assert result["asset_tag"] == "ASSET-1001"
        assert result["category"] == "Computer"
        assert result["cost"] == 3499.0
        assert result["assigned_to_id"] == "sn-u004"
        assert result["install_status"] == "In use"
        assert result["is_assigned"] is True
        assert result["source"] == "servicenow"

    def test_asset_unassigned_returns_none_and_false(self):
        record = make_record("servicenow", "asset", "sn-a007", {
            "sys_id": "sn-a007",
            "name": "Cisco Meraki MX67",
            "asset_tag": "ASSET-1007",
            "model_category": "Network",
            "assigned_to": None,
            "cost": 2100.0,
            "install_status": "Installed",
        })
        result = normalize(record)
        assert result["assigned_to_id"] is None
        assert result["is_assigned"] is False

    def test_asset_cost_is_float(self):
        record = make_record("servicenow", "asset", "sn-a002", {
            "sys_id": "sn-a002", "cost": "1799", "assigned_to": None,
        })
        result = normalize(record)
        assert isinstance(result["cost"], float)
        assert result["cost"] == 1799.0

    def test_asset_assigned_to_plain_string(self):
        """Falls back gracefully when assigned_to is a plain string (non-OData format)."""
        record = make_record("servicenow", "asset", "sn-a003", {
            "sys_id": "sn-a003",
            "assigned_to": "sn-u010",
        })
        result = normalize(record)
        assert result["assigned_to_id"] == "sn-u010"
        assert result["is_assigned"] is True

    def test_asset_mobile_category(self):
        record = make_record("servicenow", "asset", "sn-a004", {
            "sys_id": "sn-a004",
            "name": "iPhone 15 Pro",
            "asset_tag": "ASSET-1004",
            "model_category": "Mobile",
            "assigned_to": {"value": "sn-u001"},
            "cost": 999.0,
            "install_status": "In use",
        })
        result = normalize(record)
        assert result["category"] == "Mobile"
        assert result["name"] == "iPhone 15 Pro"

    def test_provenance_tags(self):
        record = make_record("servicenow", "asset", "sn-a-prv", {
            "sys_id": "sn-a-prv", "assigned_to": None,
        })
        result = normalize(record)
        assert result["_source_connector"] == "servicenow"
        assert result["_source_id"] == "sn-a-prv"
