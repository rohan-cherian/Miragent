"""
scout/ingestion/normalizer.py — Translates raw connector records to canonical dicts.

This is the Rosetta Stone of Scout's ingestion pipeline.

The problem it solves:
  Salesforce calls an employee's role: payload["Title"]
  Workday calls the same field:        payload["jobTitle"]
  Okta calls it:                       payload["profile"]["title"]
  Canonical name:                      "job_title"

The normalizer knows the mapping for each connector+entity_type pair.
Output is always a consistent canonical dict, regardless of source.

Adding a new connector = adding one new _normalize_* function.
Nothing else in the pipeline changes.

DESIGN PRINCIPLE: Be lenient on input, strict on output.
  - If a source field is missing, use None (don't crash)
  - If a source field has an unexpected type, coerce gracefully
  - The output dict must always have the same keys
"""

import logging
from typing import Any

from scout.connectors.models import RawRecord

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────

def normalize(record: RawRecord) -> dict[str, Any] | None:
    """
    Translate a RawRecord into a canonical dict.

    Returns None if the record type is not supported (with a log warning).
    The pipeline skips None records — it doesn't crash.

    Routing logic: connector_id + entity_type → the right normalizer function.
    """
    key = (record.connector_id, record.entity_type)

    normalizer_map = {
        # ── Existing connectors ───────────────────────────
        ("salesforce", "user"):        _normalize_salesforce_user,
        ("salesforce", "account"):     _normalize_salesforce_account,
        ("salesforce", "opportunity"): _normalize_salesforce_opportunity,
        ("workday",    "worker"):      _normalize_workday_worker,
        ("workday",    "department"):  _normalize_workday_department,
        ("netsuite",   "vendor"):      _normalize_netsuite_vendor,
        ("netsuite",   "invoice"):     _normalize_netsuite_invoice,
        # ── HCM ──────────────────────────────────────────
        ("bamboohr",   "employee"):    _normalize_bamboohr_employee,
        ("adp",        "worker"):      _normalize_adp_worker,
        ("rippling",   "employee"):    _normalize_rippling_employee,
        ("ukg",        "employee"):    _normalize_ukg_employee,
        ("gusto",      "employee"):    _normalize_gusto_employee,
        # ── CRM ──────────────────────────────────────────
        ("hubspot",       "contact"):       _normalize_hubspot_contact,
        ("hubspot",       "company"):       _normalize_hubspot_company,
        ("dynamics_crm",  "contact"):       _normalize_dynamics_crm_contact,
        ("dynamics_crm",  "account"):       _normalize_dynamics_crm_account,
        ("pipedrive",     "person"):        _normalize_pipedrive_person,
        ("pipedrive",     "organization"):  _normalize_pipedrive_organization,
        ("zoho",          "contact"):       _normalize_zoho_contact,
        ("zoho",          "account"):       _normalize_zoho_account,
        # ── ERP ──────────────────────────────────────────
        ("quickbooks",       "vendor"):     _normalize_quickbooks_vendor,
        ("sap",              "vendor"):     _normalize_sap_vendor,
        ("sap",              "employee"):   _normalize_sap_employee,
        ("dynamics_finance", "vendor"):     _normalize_dynamics_finance_vendor,
        ("dynamics_finance", "worker"):     _normalize_dynamics_finance_worker,
        ("sage_intacct",     "vendor"):     _normalize_sage_intacct_vendor,
        ("acumatica",        "vendor"):     _normalize_acumatica_vendor,
        ("acumatica",        "employee"):   _normalize_acumatica_employee,
        ("epicor",           "vendor"):     _normalize_epicor_vendor,
        ("epicor",           "employee"):   _normalize_epicor_employee,
        # ── Identity ─────────────────────────────────────
        ("okta",             "user"):       _normalize_okta_user,
        ("azure_ad",         "user"):       _normalize_azure_ad_user,
        ("google_workspace", "user"):       _normalize_google_workspace_user,
        ("jumpcloud",        "user"):       _normalize_jumpcloud_user,
        # ── ITSM ─────────────────────────────────────────
        ("servicenow",   "user"):       _normalize_servicenow_user,
        ("jira",         "user"):       _normalize_jira_user,
        ("zendesk",      "user"):       _normalize_zendesk_user,
        ("freshservice", "user"):       _normalize_freshservice_user,
        # ── Finance / Spend ───────────────────────────────
        ("coupa",   "supplier"):        _normalize_coupa_supplier,
        ("ramp",    "merchant"):        _normalize_ramp_merchant,
        ("ramp",    "transaction"):     _normalize_ramp_transaction,
        ("brex",    "vendor"):          _normalize_brex_vendor,
        ("concur",  "vendor"):          _normalize_concur_vendor,
        ("concur",  "expense_report"):  _normalize_concur_expense_report,
        ("billcom", "vendor"):          _normalize_billcom_vendor,
        # ── ITSM extended ────────────────────────────────────
        ("servicenow",   "asset"):      _normalize_servicenow_asset,
    }

    fn = normalizer_map.get(key)
    if fn is None and key in normalizer_map:
        # Explicitly mapped to None → future sprint entity type, skip silently
        logger.debug(f"Entity type ({record.connector_id}, {record.entity_type}) deferred to future sprint — skipping")
        return None
    if fn is None:
        logger.warning(f"No normalizer for ({record.connector_id}, {record.entity_type}) — skipping")
        return None

    try:
        result = fn(record)
        # Always tag with provenance
        result["_source_connector"] = record.connector_id
        result["_source_id"] = record.source_id
        result["_entity_type"] = record.entity_type
        result["_tenant_id"] = record.tenant_id
        return result
    except Exception as e:
        logger.error(f"Normalizer failed for {record.connector_id}/{record.entity_type}/{record.source_id}: {e}")
        return None


# ─────────────────────────────────────────────────────────
# SALESFORCE NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_salesforce_user(record: RawRecord) -> dict[str, Any]:
    """
    Salesforce User → canonical person dict.

    Salesforce field → Canonical field:
      Id            → salesforce_id
      Name          → full_name
      Email         → email           (primary resolution key)
      Title         → job_title
      Department    → department
      IsActive      → is_active
      LastLoginDate → last_login_sfdc
    """
    p = record.payload
    return {
        "entity_type": "person",
        "salesforce_id": p.get("Id"),
        "email": _clean_email(p.get("Email")),
        "full_name": p.get("Name", "").strip(),
        "job_title": p.get("Title"),
        "department": p.get("Department"),
        "is_active": p.get("IsActive", True),
        "last_login_sfdc": p.get("LastLoginDate"),
        # Salesforce doesn't give us employment type or manager
        # Those come from Workday (higher priority source of truth)
        "employment_type": None,
        "employee_id": None,
        "manager_source_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_salesforce_account(record: RawRecord) -> dict[str, Any]:
    """Salesforce Account → canonical account dict."""
    p = record.payload
    return {
        "entity_type": "account",
        "salesforce_id": p.get("Id"),
        "name": p.get("Name", "").strip(),
        "industry": p.get("Industry"),
        "account_type": p.get("Type"),
        "annual_revenue": _to_float(p.get("AnnualRevenue")),
        "employee_count": _to_int(p.get("NumberOfEmployees")),
        # OwnerId is a Salesforce user ID — we'll resolve it to canonical_id
        # during the entity resolution step
        "owner_salesforce_id": p.get("OwnerId"),
    }


def _normalize_salesforce_opportunity(record: RawRecord) -> dict[str, Any]:
    """Salesforce Opportunity → canonical opportunity dict."""
    p = record.payload
    return {
        "entity_type": "opportunity",
        "salesforce_id": p.get("Id"),
        "_source_id": p.get("Id"),
        "_source_connector": "salesforce",
        "name": p.get("Name", "").strip(),
        "stage": p.get("StageName"),
        "amount": _to_float(p.get("Amount")),
        "close_date": p.get("CloseDate"),
        "created_date": p.get("CreatedDate"),
        "probability": _to_int(p.get("Probability")),
        "is_closed": p.get("IsClosed", False),
        "is_won": p.get("IsWon", False),
        "account_salesforce_id": p.get("AccountId"),
        "owner_salesforce_id": p.get("OwnerId"),
    }


# ─────────────────────────────────────────────────────────
# WORKDAY NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_workday_worker(record: RawRecord) -> dict[str, Any]:
    """
    Workday Worker → canonical person dict.

    Workday is the SOURCE OF TRUTH for people data.
    Fields from Workday override the same fields from Salesforce.

    Workday field → Canonical field:
      workerId      → workday_id
      name          → full_name      (Workday wins)
      email         → email          (primary resolution key)
      jobTitle      → job_title      (Workday wins)
      department    → department     (Workday wins)
      managerId     → manager_workday_id  (used to build MANAGES edges)
      employmentType→ employment_type (Workday wins — critical for cost analysis)
      costCenter    → cost_center    (Workday wins)
    """
    p = record.payload
    return {
        "entity_type": "person",
        "workday_id": p.get("workerId"),
        "email": _clean_email(p.get("email")),
        "full_name": p.get("name", "").strip(),
        "employee_id": p.get("employeeId"),
        "job_title": p.get("jobTitle"),
        "department": p.get("department"),
        "is_active": p.get("isActive", True),
        "employment_type": p.get("employmentType", "Regular"),
        "location": p.get("location"),
        "cost_center": p.get("costCenter"),
        "start_date": p.get("startDate"),
        # managerId in Workday is a workday_id — resolved to canonical_id later
        "manager_workday_id": p.get("managerId"),
        "last_login_sfdc": None,
        "salesforce_id": None,
    }


def _normalize_workday_department(record: RawRecord) -> dict[str, Any]:
    """Workday Department → canonical department dict."""
    p = record.payload
    return {
        "entity_type": "department",
        "workday_id": p.get("departmentId"),
        "name": p.get("name", "").strip(),
        "cost_center": p.get("costCenter"),
        "manager_workday_id": p.get("managerId"),
        "parent_workday_id": p.get("parentDepartmentId"),
        "headcount": _to_int(p.get("headcount")),
    }


# ─────────────────────────────────────────────────────────
# NETSUITE NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_netsuite_vendor(record: RawRecord) -> dict[str, Any]:
    """
    NetSuite Vendor → canonical vendor dict.

    NetSuite field → Canonical field:
      internalId      → netsuite_id
      entityId        → name
      category        → category
      annualSpend     → annual_spend
      contractRenewal → contract_renewal
    """
    p = record.payload
    name = p.get("entityId", "").strip()
    return {
        "entity_type": "vendor",
        "netsuite_id": p.get("internalId"),
        "name": name,
        "normalized_name": name.lower().replace(" ", "-").replace(",", "").replace(".", ""),
        "category": p.get("category"),
        "email": _clean_email(p.get("email")),
        "phone": p.get("phone"),
        "is_active": p.get("isActive", True),
        "annual_spend": _to_float(p.get("annualSpend")),
        "payment_terms": p.get("paymentTerms"),
        "contract_renewal": p.get("contractRenewal"),
        "primary_contact": p.get("primaryContact"),
    }


def _normalize_netsuite_invoice(record: RawRecord) -> dict[str, Any]:
    """NetSuite AP Invoice → canonical invoice dict."""
    p = record.payload
    return {
        "entity_type": "invoice",
        "netsuite_id": p.get("internalId"),
        "vendor_netsuite_id": p.get("vendorId"),
        "transaction_date": p.get("tranDate"),
        "due_date": p.get("dueDate"),
        "amount": _to_float(p.get("amount")),
        "status": p.get("status"),
        "memo": p.get("memo"),
    }


# ─────────────────────────────────────────────────────────
# HCM NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_bamboohr_employee(record: RawRecord) -> dict[str, Any]:
    """BambooHR Employee → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("workEmail")),
        "full_name": full_name,
        "employee_id": p.get("employeeId"),
        "job_title": p.get("jobTitle"),
        "department": p.get("department"),
        "is_active": p.get("employmentStatus", "").lower() == "active",
        "employment_type": "Regular",
        "location": p.get("location"),
        "start_date": p.get("hireDate"),
        "manager_source_id": p.get("supervisorId"),
        "workday_id": None,
        "salesforce_id": None,
        "cost_center": None,
    }


def _normalize_adp_worker(record: RawRecord) -> dict[str, Any]:
    """ADP Worker → canonical person dict."""
    p = record.payload
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": p.get("fullName", "").strip(),
        "employee_id": p.get("workerId"),
        "job_title": p.get("positionTitle"),
        "department": p.get("department"),
        "is_active": p.get("workerStatus", "").lower() == "active",
        "employment_type": p.get("employeeType", "Regular"),
        "start_date": p.get("startDate"),
        "manager_source_id": p.get("managerId"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
    }


def _normalize_rippling_employee(record: RawRecord) -> dict[str, Any]:
    """Rippling Employee → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": full_name,
        "employee_id": p.get("id"),
        "job_title": p.get("title"),
        "department": p.get("department"),
        "is_active": True,  # Rippling doesn't have explicit status in fixture
        "employment_type": p.get("employmentType", "Full-Time"),
        "location": p.get("workLocation"),
        "start_date": p.get("startDate"),
        "manager_source_id": p.get("managerId"),
        "workday_id": None,
        "salesforce_id": None,
        "cost_center": None,
    }


def _normalize_ukg_employee(record: RawRecord) -> dict[str, Any]:
    """UKG Employee → canonical person dict."""
    p = record.payload
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("emailAddress")),
        "full_name": p.get("fullName", "").strip(),
        "employee_id": p.get("personNumber"),
        "job_title": p.get("jobTitle"),
        "department": p.get("orgUnitDescription"),
        "is_active": p.get("employeeStatus", "").lower() == "active",
        "employment_type": "Regular",
        "start_date": p.get("hireDate"),
        "manager_source_id": p.get("supervisorPersonNumber"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
    }


def _normalize_gusto_employee(record: RawRecord) -> dict[str, Any]:
    """Gusto Employee → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": full_name,
        "employee_id": p.get("uuid"),
        "job_title": p.get("job_title"),
        "department": p.get("department"),
        "is_active": True,
        "employment_type": p.get("employment_type", "Full-Time"),
        "start_date": p.get("start_date"),
        "manager_source_id": p.get("manager_uuid"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
    }


# ─────────────────────────────────────────────────────────
# CRM NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_hubspot_contact(record: RawRecord) -> dict[str, Any]:
    """HubSpot Contact → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('firstname', '')} {p.get('lastname', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": full_name,
        "job_title": p.get("jobtitle"),
        "department": p.get("department"),
        "is_active": True,
        "employment_type": None,
        "employee_id": None,
        "manager_source_id": None,
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_hubspot_company(record: RawRecord) -> dict[str, Any]:
    """HubSpot Company → canonical account dict."""
    p = record.payload
    return {
        "entity_type": "account",
        "name": p.get("name", "").strip(),
        "industry": p.get("industry"),
        "account_type": None,
        "annual_revenue": _to_float(p.get("annualrevenue")),
        "employee_count": _to_int(p.get("numberofemployees")),
        "owner_salesforce_id": p.get("ownerId"),
        "salesforce_id": None,
    }


def _normalize_dynamics_crm_contact(record: RawRecord) -> dict[str, Any]:
    """Dynamics CRM Contact → canonical person dict."""
    p = record.payload
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("emailaddress1")),
        "full_name": p.get("fullname", "").strip(),
        "job_title": p.get("jobtitle"),
        "department": p.get("departmentname"),
        "is_active": p.get("statecode", 0) == 0,
        "employment_type": None,
        "employee_id": None,
        "manager_source_id": None,
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_dynamics_crm_account(record: RawRecord) -> dict[str, Any]:
    """Dynamics CRM Account → canonical account dict."""
    p = record.payload
    return {
        "entity_type": "account",
        "name": p.get("name", "").strip(),
        "industry": str(p.get("industrycode", "")),
        "account_type": p.get("accounttype"),
        "annual_revenue": _to_float(p.get("revenue")),
        "employee_count": _to_int(p.get("numberofemployees")),
        "owner_salesforce_id": p.get("ownerid"),
        "salesforce_id": None,
    }


def _normalize_pipedrive_person(record: RawRecord) -> dict[str, Any]:
    """Pipedrive Person → canonical person dict."""
    p = record.payload
    email_list = p.get("email", [])
    email = None
    if isinstance(email_list, list) and email_list:
        email = next((e.get("value") for e in email_list if e.get("primary")), email_list[0].get("value") if email_list else None)
    return {
        "entity_type": "person",
        "email": _clean_email(email),
        "full_name": p.get("name", "").strip(),
        "job_title": p.get("job_title"),
        "department": None,
        "is_active": p.get("active_flag", True),
        "employment_type": None,
        "employee_id": None,
        "manager_source_id": None,
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_pipedrive_organization(record: RawRecord) -> dict[str, Any]:
    """Pipedrive Organization → canonical account dict."""
    p = record.payload
    return {
        "entity_type": "account",
        "name": p.get("name", "").strip(),
        "industry": p.get("industry"),
        "account_type": None,
        "annual_revenue": None,
        "employee_count": None,
        "owner_salesforce_id": None,
        "salesforce_id": None,
    }


def _normalize_zoho_contact(record: RawRecord) -> dict[str, Any]:
    """Zoho CRM Contact → canonical person dict."""
    p = record.payload
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("Email")),
        "full_name": p.get("Full_Name", "").strip(),
        "job_title": p.get("Title"),
        "department": p.get("Department"),
        "is_active": True,
        "employment_type": None,
        "employee_id": None,
        "manager_source_id": None,
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_zoho_account(record: RawRecord) -> dict[str, Any]:
    """Zoho CRM Account → canonical account dict."""
    p = record.payload
    owner = p.get("Owner", {})
    owner_id = owner.get("id") if isinstance(owner, dict) else None
    return {
        "entity_type": "account",
        "name": p.get("Account_Name", "").strip(),
        "industry": p.get("Industry"),
        "account_type": None,
        "annual_revenue": _to_float(p.get("Annual_Revenue")),
        "employee_count": _to_int(p.get("Employees")),
        "owner_salesforce_id": owner_id,
        "salesforce_id": None,
    }


# ─────────────────────────────────────────────────────────
# ERP NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_vendor_common(name: str, annual_spend: float | None, category: str | None, is_active: bool, payment_terms: str | None = None, contract_renewal: str | None = None) -> dict[str, Any]:
    """Common vendor normalization helper."""
    name = name.strip()
    return {
        "entity_type": "vendor",
        "name": name,
        "normalized_name": name.lower().replace(" ", "-").replace(",", "").replace(".", ""),
        "category": category,
        "email": None,
        "phone": None,
        "is_active": is_active,
        "annual_spend": _to_float(annual_spend),
        "payment_terms": payment_terms,
        "contract_renewal": contract_renewal,
        "primary_contact": None,
        "netsuite_id": None,
    }


def _normalize_quickbooks_vendor(record: RawRecord) -> dict[str, Any]:
    """QuickBooks Vendor → canonical vendor dict."""
    p = record.payload
    result = _normalize_vendor_common(
        name=p.get("DisplayName", ""),
        annual_spend=p.get("annual_spend"),
        category=p.get("vendor_type"),
        is_active=True,
    )
    return result


def _normalize_sap_vendor(record: RawRecord) -> dict[str, Any]:
    """SAP Vendor → canonical vendor dict."""
    p = record.payload
    result = _normalize_vendor_common(
        name=p.get("VendorName", ""),
        annual_spend=p.get("AnnualSpend"),
        category=p.get("AccountGroup"),
        is_active=True,
        payment_terms=p.get("PaymentTerms"),
    )
    return result


def _normalize_sap_employee(record: RawRecord) -> dict[str, Any]:
    """SAP Employee → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("Email")),
        "full_name": full_name,
        "employee_id": p.get("EmployeeId"),
        "job_title": p.get("Position"),
        "department": p.get("OrganizationalUnit"),
        "is_active": True,
        "employment_type": p.get("ContractType", "Permanent"),
        "manager_source_id": p.get("ManagerId"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_dynamics_finance_vendor(record: RawRecord) -> dict[str, Any]:
    """Dynamics Finance Vendor → canonical vendor dict."""
    p = record.payload
    return _normalize_vendor_common(
        name=p.get("Name") or p.get("VendorName", ""),
        annual_spend=p.get("AnnualSpend"),
        category=p.get("VendorGroupId"),
        is_active=True,
        payment_terms=p.get("PaymentTermId") or f"Net {p.get('PaymentTermBaseDays', 30)}",
    )


def _normalize_dynamics_finance_worker(record: RawRecord) -> dict[str, Any]:
    """
    Dynamics 365 Finance Worker → canonical person dict.

    Dynamics F&O field → Canonical field:
      PersonnelNumber      → employee_id
      PrimaryWorkerName    → full_name
      PrimaryEmailAddress  → email
      WorkerType           → employment_type ("Employee" / "Contractor")
      OfficeLocation       → location
    """
    p = record.payload
    worker_type = p.get("WorkerType", "Employee")
    employment_type = "Regular" if worker_type == "Employee" else "Contractor"
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("PrimaryEmailAddress")),
        "full_name": p.get("PrimaryWorkerName") or p.get("PersonnelNumber"),
        "employee_id": p.get("PersonnelNumber"),
        "job_title": None,
        "department": None,
        "is_active": True,
        "employment_type": employment_type,
        "manager_source_id": None,
        "workday_id": None,
        "salesforce_id": None,
        "location": p.get("OfficeLocation"),
        "cost_center": None,
        "start_date": None,
    }


def _normalize_sage_intacct_vendor(record: RawRecord) -> dict[str, Any]:
    """Sage Intacct Vendor → canonical vendor dict."""
    p = record.payload
    return _normalize_vendor_common(
        name=p.get("NAME", ""),
        annual_spend=p.get("ANNUALSPEND"),
        category=p.get("VENDTYPE"),
        is_active=p.get("STATUS", "active").lower() == "active",
    )


def _normalize_acumatica_vendor(record: RawRecord) -> dict[str, Any]:
    """Acumatica Vendor → canonical vendor dict."""
    p = record.payload

    def _av(field: Any) -> Any:
        """Unwrap Acumatica OData field: {"value": "..."} → raw value."""
        if isinstance(field, dict):
            return field.get("value")
        return field

    name = _av(p.get("VendorName")) or ""
    status = _av(p.get("Status")) or "Active"
    category = _av(p.get("VendorClass"))
    annual_spend = _av(p.get("AnnualSpend"))
    return _normalize_vendor_common(
        name=name,
        annual_spend=annual_spend,
        category=category,
        is_active=status.lower() == "active",
    )


def _normalize_acumatica_employee(record: RawRecord) -> dict[str, Any]:
    """
    Acumatica Employee → canonical person dict.

    Acumatica fields are OData-wrapped: {"value": "...", "type": "string"}.

    Acumatica field   → Canonical field:
      EmployeeID      → employee_id
      Status          → is_active ("Active" / "Inactive")
      DepartmentID    → department
      PositionID      → job_title
      ReportsToID     → manager_source_id
      Email           → email
    """
    p = record.payload

    def _av(field: Any) -> Any:
        if isinstance(field, dict):
            return field.get("value")
        return field

    status = _av(p.get("Status")) or "Active"
    return {
        "entity_type": "person",
        "email": _clean_email(_av(p.get("Email"))),
        "full_name": _av(p.get("EmployeeID")),   # Acumatica uses employee ID as display name
        "employee_id": _av(p.get("EmployeeID")),
        "job_title": _av(p.get("PositionID")),
        "department": _av(p.get("DepartmentID")),
        "is_active": status.lower() == "active",
        "employment_type": "Regular",
        "manager_source_id": _av(p.get("ReportsToID")),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_epicor_vendor(record: RawRecord) -> dict[str, Any]:
    """Epicor Vendor → canonical vendor dict."""
    p = record.payload
    return _normalize_vendor_common(
        name=p.get("Name", ""),
        annual_spend=p.get("AnnualSpend"),
        category=p.get("VendorType"),
        is_active=True,
        payment_terms=p.get("TermsCode"),
    )


def _normalize_epicor_employee(record: RawRecord) -> dict[str, Any]:
    """Epicor Employee → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("Email")),
        "full_name": full_name,
        "employee_id": p.get("EmpID"),
        "job_title": p.get("EmpRoleCode"),
        "department": p.get("DeptDescription"),
        "is_active": True,
        "employment_type": "Regular",
        "manager_source_id": p.get("SupervisorID"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


# ─────────────────────────────────────────────────────────
# IDENTITY NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_okta_user(record: RawRecord) -> dict[str, Any]:
    """Okta User → canonical person dict."""
    p = record.payload
    profile = p.get("profile", {})
    return {
        "entity_type": "person",
        "okta_id": p.get("id"),
        "email": _clean_email(profile.get("email")),
        "full_name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
        "job_title": profile.get("title"),
        "department": profile.get("department"),
        "is_active": p.get("status", "").upper() == "ACTIVE",
        "employment_type": None,
        "employee_id": None,
        "manager_source_id": profile.get("managerId"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_azure_ad_user(record: RawRecord) -> dict[str, Any]:
    """Azure AD User → canonical person dict."""
    p = record.payload
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("mail")),
        "full_name": p.get("displayName", "").strip(),
        "job_title": p.get("jobTitle"),
        "department": p.get("department"),
        "is_active": p.get("accountEnabled", True),
        "employment_type": "Contractor" if p.get("userType") == "Guest" else "Regular",
        "employee_id": None,
        "manager_source_id": p.get("managerId"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_google_workspace_user(record: RawRecord) -> dict[str, Any]:
    """Google Workspace User → canonical person dict."""
    p = record.payload
    name_obj = p.get("name", {})
    orgs = p.get("organizations", [{}])
    org = orgs[0] if orgs else {}
    relations = p.get("relations", [])
    manager_email = relations[0].get("value") if relations else None
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("primaryEmail")),
        "full_name": name_obj.get("fullName", "").strip(),
        "job_title": org.get("title"),
        "department": org.get("department"),
        "is_active": not p.get("suspended", False),
        "employment_type": "Regular",
        "employee_id": None,
        "manager_source_id": manager_email,  # Google uses manager email
        "workday_id": None,
        "salesforce_id": None,
        "location": p.get("orgUnitPath"),
        "cost_center": None,
        "start_date": None,
    }


def _normalize_jumpcloud_user(record: RawRecord) -> dict[str, Any]:
    """JumpCloud User → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('firstname', '')} {p.get('lastname', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": full_name,
        "job_title": p.get("job_title"),
        "department": p.get("department"),
        "is_active": p.get("activated", True) and not p.get("account_locked", False),
        "employment_type": "Regular",
        "employee_id": None,
        "manager_source_id": p.get("manager"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


# ─────────────────────────────────────────────────────────
# ITSM NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_servicenow_user(record: RawRecord) -> dict[str, Any]:
    """ServiceNow User → canonical person dict."""
    p = record.payload
    manager = p.get("manager", {})
    manager_id = manager.get("value") if isinstance(manager, dict) else None
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": p.get("name", "").strip(),
        "job_title": p.get("title"),
        "department": p.get("department"),
        "is_active": p.get("active", True),
        "employment_type": "Regular",
        "employee_id": None,
        "manager_source_id": manager_id,
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_jira_user(record: RawRecord) -> dict[str, Any]:
    """Jira User → canonical person dict."""
    p = record.payload
    # Jira uses atlassian.net domain emails
    email = _clean_email(p.get("emailAddress"))
    return {
        "entity_type": "person",
        "email": email,
        "full_name": p.get("displayName", "").strip(),
        "job_title": None,
        "department": None,
        "is_active": p.get("active", True),
        "employment_type": "Regular" if p.get("accountType") == "atlassian" else "Contractor",
        "employee_id": None,
        "manager_source_id": None,
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_zendesk_user(record: RawRecord) -> dict[str, Any]:
    """Zendesk User → canonical person dict."""
    p = record.payload
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": p.get("name", "").strip(),
        "job_title": p.get("job_title"),
        "department": None,
        "is_active": p.get("active", True),
        "employment_type": "Regular",
        "employee_id": None,
        "manager_source_id": None,
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


def _normalize_freshservice_user(record: RawRecord) -> dict[str, Any]:
    """Freshservice User → canonical person dict."""
    p = record.payload
    full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    return {
        "entity_type": "person",
        "email": _clean_email(p.get("email")),
        "full_name": full_name,
        "job_title": p.get("job_title"),
        "department": p.get("department"),
        "is_active": p.get("active", True),
        "employment_type": "Regular",
        "employee_id": None,
        "manager_source_id": p.get("reporting_manager_id"),
        "workday_id": None,
        "salesforce_id": None,
        "location": None,
        "cost_center": None,
        "start_date": None,
    }


# ─────────────────────────────────────────────────────────
# FINANCE / SPEND NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_coupa_supplier(record: RawRecord) -> dict[str, Any]:
    """Coupa Supplier → canonical vendor dict."""
    p = record.payload
    payment_term = p.get("payment_term", {})
    payment_code = payment_term.get("code") if isinstance(payment_term, dict) else None
    name = p.get("name", "").strip()
    return {
        "entity_type": "vendor",
        "name": name,
        "normalized_name": name.lower().replace(" ", "-").replace(",", "").replace(".", ""),
        "category": p.get("supplier_type"),
        "email": None,
        "phone": None,
        "is_active": p.get("status", "active").lower() == "active",
        "annual_spend": _to_float(p.get("total_invoiced_amount")),
        "payment_terms": payment_code,
        "contract_renewal": p.get("contract_expiry_date"),
        "primary_contact": None,
        "netsuite_id": None,
    }


def _normalize_ramp_merchant(record: RawRecord) -> dict[str, Any]:
    """Ramp Merchant → canonical vendor dict."""
    p = record.payload
    name = p.get("name", "").strip()
    return {
        "entity_type": "vendor",
        "name": name,
        "normalized_name": name.lower().replace(" ", "-").replace(",", "").replace(".", ""),
        "category": p.get("category_name"),
        "email": None,
        "phone": None,
        "is_active": True,
        "annual_spend": _to_float(p.get("total_spend_ytd")),
        "payment_terms": None,
        "contract_renewal": None,
        "primary_contact": None,
        "netsuite_id": None,
    }


def _normalize_brex_vendor(record: RawRecord) -> dict[str, Any]:
    """Brex Vendor → canonical vendor dict."""
    p = record.payload
    name = p.get("name", "").strip()
    return {
        "entity_type": "vendor",
        "name": name,
        "normalized_name": name.lower().replace(" ", "-").replace(",", "").replace(".", ""),
        "category": p.get("category"),
        "email": None,
        "phone": None,
        "is_active": True,
        "annual_spend": _to_float(p.get("total_spend")),
        "payment_terms": p.get("payment_method"),
        "contract_renewal": None,
        "primary_contact": None,
        "netsuite_id": None,
    }


def _normalize_concur_vendor(record: RawRecord) -> dict[str, Any]:
    """SAP Concur Vendor → canonical vendor dict."""
    p = record.payload
    name = p.get("VendorName", "").strip()
    return {
        "entity_type": "vendor",
        "name": name,
        "normalized_name": name.lower().replace(" ", "-").replace(",", "").replace(".", ""),
        "category": p.get("VendorType"),
        "email": None,
        "phone": None,
        "is_active": True,
        "annual_spend": _to_float(p.get("AnnualSpend")),
        "payment_terms": None,
        "contract_renewal": None,
        "primary_contact": None,
        "netsuite_id": None,
    }


def _normalize_billcom_vendor(record: RawRecord) -> dict[str, Any]:
    """Bill.com Vendor → canonical vendor dict."""
    p = record.payload
    name = p.get("name", "").strip()
    return {
        "entity_type": "vendor",
        "name": name,
        "normalized_name": name.lower().replace(" ", "-").replace(",", "").replace(".", ""),
        "category": p.get("accountType"),
        "email": _clean_email(p.get("email")),
        "phone": None,
        "is_active": p.get("isActive", True),
        "annual_spend": _to_float(p.get("annual_spend")),
        "payment_terms": p.get("paymentTerm"),
        "contract_renewal": None,
        "primary_contact": None,
        "netsuite_id": None,
    }


# ─────────────────────────────────────────────────────────
# SPRINT 39 — DEFERRED ENTITY NORMALIZERS
# ─────────────────────────────────────────────────────────

def _normalize_ramp_transaction(record: RawRecord) -> dict[str, Any]:
    """
    Ramp Transaction → canonical expense_transaction dict.

    Ramp transactions represent individual corporate card charges against
    a merchant. They carry amount, currency, employee, and memo data —
    valuable for spend audit and expense anomaly detection workers.
    """
    p = record.payload
    return {
        "entity_type": "expense_transaction",
        "transaction_id": p.get("id"),
        "merchant_id": p.get("merchant_id"),
        "amount": _to_float(p.get("amount")),
        "currency_code": p.get("currency_code", "USD"),
        "user_id": p.get("user_id"),
        "memo": p.get("memo"),
        "transaction_date": p.get("date"),
        "source": "ramp",
    }


def _normalize_concur_expense_report(record: RawRecord) -> dict[str, Any]:
    """
    SAP Concur Expense Report → canonical expense_report dict.

    Concur expense reports aggregate employee travel and entertainment
    spend for approval workflows. Used by the expense audit worker to
    surface T&E anomalies, policy violations, and approval bottlenecks.
    """
    p = record.payload
    return {
        "entity_type": "expense_report",
        "report_id": p.get("ReportId"),
        "employee_id": p.get("EmployeeId"),
        "employee_name": p.get("EmployeeName"),
        "total_amount": _to_float(p.get("Total")),
        "submit_date": p.get("SubmitDate"),
        "approval_status": p.get("ApprovalStatus"),
        "source": "concur",
    }


def _normalize_servicenow_asset(record: RawRecord) -> dict[str, Any]:
    """
    ServiceNow Asset → canonical asset dict.

    ServiceNow CMDB/Asset records track hardware inventory — laptops, phones,
    network gear — with cost and assignment data. Used for license management
    and hardware cost allocation analysis.

    The `assigned_to` field is a reference dict: {"value": "sn-u004"} or None.
    """
    p = record.payload

    # assigned_to is either {"value": "sys_id"} or None
    assigned_raw = p.get("assigned_to")
    assigned_to_id = None
    if isinstance(assigned_raw, dict):
        assigned_to_id = assigned_raw.get("value")
    elif assigned_raw:
        assigned_to_id = str(assigned_raw)

    return {
        "entity_type": "asset",
        "asset_id": p.get("sys_id"),
        "name": p.get("name"),
        "asset_tag": p.get("asset_tag"),
        "category": p.get("model_category"),
        "cost": _to_float(p.get("cost")),
        "assigned_to_id": assigned_to_id,
        "install_status": p.get("install_status"),
        "is_assigned": assigned_to_id is not None,
        "source": "servicenow",
    }


# ─────────────────────────────────────────────────────────
# UTILITY HELPERS
# ─────────────────────────────────────────────────────────

def _clean_email(value: Any) -> str | None:
    """Normalize email addresses — lowercase, stripped, None if empty."""
    if not value:
        return None
    cleaned = str(value).strip().lower()
    return cleaned if "@" in cleaned else None


def _to_float(value: Any) -> float | None:
    """Convert to float, return None if conversion fails."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    """Convert to int, return None if conversion fails."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
