"""
Dual column-name variants for Workday RaaS extracts + canonical normalisation.

Workday customers reconfigure report column aliases; the same worker can leave
the tenant as ``Employee_ID`` or ``Worker`` depending on the report definition.
Both variants are served on purpose so week-two reconciliation maps them to one
canonical shape.
"""

from __future__ import annotations

from typing import Any, Literal

ReportEntity = Literal["workers", "organizations"]
ReportVariant = Literal["census", "directory", "hierarchy", "structure"]

# Report name → (entity, variant)
REPORT_CATALOG: dict[str, tuple[ReportEntity, ReportVariant]] = {
    # Workers — same people, different column aliases
    "Worker_Census": ("workers", "census"),
    "Worker_Directory": ("workers", "directory"),
    # Organizations — same orgs, different column aliases
    "Organization_Hierarchy": ("organizations", "hierarchy"),
    "Org_Structure": ("organizations", "structure"),
}


def known_report_names() -> list[str]:
    return sorted(REPORT_CATALOG.keys())


# ── Project internal row → variant A / B ─────────────────────────────────────


def project_worker_census(row: dict[str, Any]) -> dict[str, Any]:
    """Variant A — classic census-style aliases (spaces → underscores)."""
    return {
        "Employee_ID": row.get("employee_id_display"),
        "Legal_Name_-_First_Name": row.get("legal_first_name"),
        "Legal_Name_-_Last_Name": row.get("legal_last_name"),
        "primaryWorkEmail": row.get("work_email"),
        "CF_Business_Title": row.get("business_title"),
        "supervisoryOrganization": row.get("sup_org_name"),
        "Manager_ID": row.get("manager_employee_id"),
        "location": row.get("location_name"),
        "employmentStatus": row.get("employment_status"),
        "hireDate": _date_str(row.get("original_hire_date")),
        "isActive": bool(row.get("is_active", True)),
        "Worker_WID": str(row.get("worker_wid")) if row.get("worker_wid") else None,
    }


def project_worker_directory(row: dict[str, Any]) -> dict[str, Any]:
    """Variant B — reconfigured directory aliases (deliberately different keys)."""
    return {
        "Worker": row.get("employee_id_display"),
        "First_Name": row.get("legal_first_name"),
        "Last_Name": row.get("legal_last_name"),
        "Email_-_Work": row.get("work_email"),
        "Job_Title": row.get("business_title"),
        "Organization": row.get("sup_org_name"),
        "Manager_Worker": row.get("manager_employee_id"),
        "Work_Location": row.get("location_name"),
        "workerStatus": row.get("employment_status"),
        "Original_Hire_Date": _date_str(row.get("original_hire_date")),
        "Active_Status": "1" if row.get("is_active", True) else "0",
        "WID": str(row.get("worker_wid")) if row.get("worker_wid") else None,
    }


def project_org_hierarchy(row: dict[str, Any]) -> dict[str, Any]:
    """Variant A — organization hierarchy report aliases."""
    return {
        "Organization_ID": str(row.get("org_wid")) if row.get("org_wid") else None,
        "Organization_Code": row.get("org_code"),
        "Organization_Name": row.get("org_name"),
        "Parent_Organization_ID": (
            str(row["superior_org_wid"]) if row.get("superior_org_wid") else None
        ),
        "Cost_Center": row.get("cost_center_code"),
        "Active": bool(row.get("is_active", True)),
    }


def project_org_structure(row: dict[str, Any]) -> dict[str, Any]:
    """Variant B — reconfigured org structure aliases."""
    return {
        "orgWID": str(row.get("org_wid")) if row.get("org_wid") else None,
        "Code": row.get("org_code"),
        "Name": row.get("org_name"),
        "Superior": (
            str(row["superior_org_wid"]) if row.get("superior_org_wid") else None
        ),
        "CostCenterCode": row.get("cost_center_code"),
        "Is_Active_Flag": "Y" if row.get("is_active", True) else "N",
    }


def project_rows(
    entity: ReportEntity,
    variant: ReportVariant,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if entity == "workers":
        fn = project_worker_census if variant == "census" else project_worker_directory
    else:
        fn = project_org_hierarchy if variant == "hierarchy" else project_org_structure
    return [fn(r) for r in rows]


def build_raas_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Workday RaaS JSON wrapper."""
    return {"Report_Entry": entries}


# ── Canonical normalisation (both variants → one shape) ─────────────────────


CANONICAL_WORKER_KEYS = (
    "worker_id",
    "worker_wid",
    "first_name",
    "last_name",
    "email",
    "title",
    "org_name",
    "manager_id",
    "location",
    "employment_status",
    "hire_date",
    "is_active",
)

CANONICAL_ORG_KEYS = (
    "org_id",
    "org_code",
    "org_name",
    "parent_org_id",
    "cost_center",
    "is_active",
)


def normalize_worker_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """
    Map either Worker_Census or Worker_Directory columns to canonical worker.

    Detection is by key presence — not by report name — so a client that only
    sees the payload can still normalise.
    """
    if "Employee_ID" in entry or "Legal_Name_-_First_Name" in entry:
        return {
            "worker_id": entry.get("Employee_ID"),
            "worker_wid": entry.get("Worker_WID"),
            "first_name": entry.get("Legal_Name_-_First_Name"),
            "last_name": entry.get("Legal_Name_-_Last_Name"),
            "email": entry.get("primaryWorkEmail"),
            "title": entry.get("CF_Business_Title"),
            "org_name": entry.get("supervisoryOrganization"),
            "manager_id": entry.get("Manager_ID"),
            "location": entry.get("location"),
            "employment_status": entry.get("employmentStatus"),
            "hire_date": entry.get("hireDate"),
            "is_active": bool(entry.get("isActive", True)),
        }

    if "Worker" in entry or "Email_-_Work" in entry:
        active_raw = entry.get("Active_Status")
        if isinstance(active_raw, bool):
            is_active = active_raw
        else:
            is_active = str(active_raw).strip() in {"1", "Y", "y", "true", "True"}
        return {
            "worker_id": entry.get("Worker"),
            "worker_wid": entry.get("WID"),
            "first_name": entry.get("First_Name"),
            "last_name": entry.get("Last_Name"),
            "email": entry.get("Email_-_Work"),
            "title": entry.get("Job_Title"),
            "org_name": entry.get("Organization"),
            "manager_id": entry.get("Manager_Worker"),
            "location": entry.get("Work_Location"),
            "employment_status": entry.get("workerStatus"),
            "hire_date": entry.get("Original_Hire_Date"),
            "is_active": is_active,
        }

    raise ValueError("Unrecognised worker report columns — cannot normalise")


def normalize_organization_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Map either Organization_Hierarchy or Org_Structure columns to canonical org."""
    if "Organization_ID" in entry or "Organization_Name" in entry:
        return {
            "org_id": entry.get("Organization_ID"),
            "org_code": entry.get("Organization_Code"),
            "org_name": entry.get("Organization_Name"),
            "parent_org_id": entry.get("Parent_Organization_ID"),
            "cost_center": entry.get("Cost_Center"),
            "is_active": bool(entry.get("Active", True)),
        }

    if "orgWID" in entry or "CostCenterCode" in entry:
        flag = entry.get("Is_Active_Flag")
        if isinstance(flag, bool):
            is_active = flag
        else:
            is_active = str(flag).strip().upper() in {"Y", "1", "TRUE"}
        return {
            "org_id": entry.get("orgWID"),
            "org_code": entry.get("Code"),
            "org_name": entry.get("Name"),
            "parent_org_id": entry.get("Superior"),
            "cost_center": entry.get("CostCenterCode"),
            "is_active": is_active,
        }

    raise ValueError("Unrecognised organization report columns — cannot normalise")


def normalize_report_entries(
    entries: list[dict[str, Any]],
    *,
    entity: ReportEntity,
) -> list[dict[str, Any]]:
    if entity == "workers":
        return [normalize_worker_entry(e) for e in entries]
    return [normalize_organization_entry(e) for e in entries]


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:10]
