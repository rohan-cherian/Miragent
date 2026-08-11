"""In-memory Workday store for unit tests (no Postgres required)."""

from __future__ import annotations

from typing import Any


class WorkdayStore:
    """Seedable in-memory backend — inject via ``create_workday_app(store=...)``."""

    backend_name = "memory"

    def __init__(self) -> None:
        self.workers: list[dict[str, Any]] = []
        self.organizations: list[dict[str, Any]] = []

    def seed_defaults(self) -> None:
        self.organizations = [
            {
                "org_wid": "11111111-1111-1111-1111-111111111101",
                "org_code": "ENG",
                "org_name": "Engineering",
                "superior_org_wid": None,
                "cost_center_code": "CC-100",
                "is_active": True,
            },
            {
                "org_wid": "11111111-1111-1111-1111-111111111102",
                "org_code": "PLAT",
                "org_name": "Platform",
                "superior_org_wid": "11111111-1111-1111-1111-111111111101",
                "cost_center_code": "CC-110",
                "is_active": True,
            },
        ]
        self.workers = [
            {
                "worker_wid": "22222222-2222-2222-2222-222222222201",
                "employee_id_display": "E1001",
                "legal_first_name": "Ada",
                "legal_last_name": "Lovelace",
                "work_email": "ada@example.com",
                "business_title": "Principal Engineer",
                "sup_org_name": "Platform",
                "manager_employee_id": None,
                "location_name": "London",
                "employment_status": "Active",
                "original_hire_date": "2020-01-15",
                "is_active": True,
            },
            {
                "worker_wid": "22222222-2222-2222-2222-222222222202",
                "employee_id_display": "E1002",
                "legal_first_name": "Grace",
                "legal_last_name": "Hopper",
                "work_email": "grace@example.com",
                "business_title": "Staff Engineer",
                "sup_org_name": "Platform",
                "manager_employee_id": "E1001",
                "location_name": "New York",
                "employment_status": "Active",
                "original_hire_date": "2021-06-01",
                "is_active": True,
            },
            {
                "worker_wid": "22222222-2222-2222-2222-222222222203",
                "employee_id_display": "E1003",
                "legal_first_name": "Alan",
                "legal_last_name": "Turing",
                "work_email": "alan@example.com",
                "business_title": "Researcher",
                "sup_org_name": "Engineering",
                "manager_employee_id": "E1001",
                "location_name": "Cambridge",
                "employment_status": "Leave",
                "original_hire_date": "2019-03-10",
                "is_active": False,
            },
        ]

    def list_workers(self, *, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        total = len(self.workers)
        return self.workers[offset : offset + limit], total

    def list_organizations(
        self, *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        total = len(self.organizations)
        return self.organizations[offset : offset + limit], total
