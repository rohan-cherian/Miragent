"""
tests/emulators/test_workday_emulator.py — W1-SRC-06 Workday RaaS emulator

Covers:
  - Dual column variants for the same workers (Census vs Directory)
  - Dual column variants for orgs (Hierarchy vs Structure)
  - Canonical normalisation maps both variants to one shape
  - Auth 401 + rate limit + report catalog via scout.shared
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scout.emulators.workday import WorkdayStore, create_workday_app
from scout.emulators.workday.factory import create_store
from scout.emulators.workday.reports import (
    normalize_organization_entry,
    normalize_report_entries,
    normalize_worker_entry,
)

AUTH = {"Authorization": "Bearer test-token"}
TENANT = "acme_dpt1"


@pytest.fixture
def store() -> WorkdayStore:
    s = WorkdayStore()
    s.seed_defaults()
    return s


@pytest.fixture
def client(store: WorkdayStore) -> TestClient:
    app = create_workday_app(store=store, rate_limit_max=1000)
    return TestClient(app)


@pytest.fixture
def tight_client(store: WorkdayStore) -> TestClient:
    app = create_workday_app(
        store=store,
        rate_limit_max=3,
        rate_limit_window_seconds=60,
    )
    return TestClient(app)


class TestAuth:
    def test_missing_token_returns_workday_401(self, client: TestClient):
        res = client.get(f"/ccx/service/customreport2/{TENANT}/Worker_Census")
        assert res.status_code == 401
        body = res.json()
        assert body["error"] == "invalid.authentication"
        assert "error_description" in body

    def test_bearer_token_accepted(self, client: TestClient):
        res = client.get(
            f"/ccx/service/customreport2/{TENANT}/Worker_Census",
            headers=AUTH,
        )
        assert res.status_code == 200


class TestReportCatalog:
    def test_lists_dual_variants(self, client: TestClient):
        res = client.get(f"/ccx/service/customreport2/{TENANT}", headers=AUTH)
        assert res.status_code == 200
        names = {r["name"] for r in res.json()["reports"]}
        assert names == {
            "Worker_Census",
            "Worker_Directory",
            "Organization_Hierarchy",
            "Org_Structure",
        }

    def test_unknown_report_404(self, client: TestClient):
        res = client.get(
            f"/ccx/service/customreport2/{TENANT}/Does_Not_Exist",
            headers=AUTH,
        )
        assert res.status_code == 404
        assert res.json()["error"] == "report.not.found"


class TestDualWorkerColumns:
    def test_census_and_directory_use_different_keys(self, client: TestClient):
        census = client.get(
            f"/ccx/service/customreport2/{TENANT}/Worker_Census",
            headers=AUTH,
        ).json()["Report_Entry"]
        directory = client.get(
            f"/ccx/service/customreport2/{TENANT}/Worker_Directory",
            headers=AUTH,
        ).json()["Report_Entry"]

        assert len(census) == len(directory) == 3
        assert "Employee_ID" in census[0]
        assert "Legal_Name_-_First_Name" in census[0]
        assert "Worker" not in census[0]

        assert "Worker" in directory[0]
        assert "Email_-_Work" in directory[0]
        assert "Employee_ID" not in directory[0]

        # Same people, different labels
        assert {r["Employee_ID"] for r in census} == {r["Worker"] for r in directory}

    def test_both_variants_normalise_to_same_canonical(self, client: TestClient):
        census = client.get(
            f"/ccx/service/customreport2/{TENANT}/Worker_Census",
            headers=AUTH,
        ).json()["Report_Entry"]
        directory = client.get(
            f"/ccx/service/customreport2/{TENANT}/Worker_Directory",
            headers=AUTH,
        ).json()["Report_Entry"]

        canon_a = normalize_report_entries(census, entity="workers")
        canon_b = normalize_report_entries(directory, entity="workers")

        # Sort by worker_id so order differences do not matter
        canon_a = sorted(canon_a, key=lambda r: r["worker_id"])
        canon_b = sorted(canon_b, key=lambda r: r["worker_id"])
        assert canon_a == canon_b

        ada = next(r for r in canon_a if r["worker_id"] == "E1001")
        assert ada["first_name"] == "Ada"
        assert ada["last_name"] == "Lovelace"
        assert ada["email"] == "ada@example.com"
        assert ada["title"] == "Principal Engineer"
        assert ada["is_active"] is True


class TestDualOrgColumns:
    def test_hierarchy_and_structure_normalise_equal(self, client: TestClient):
        hierarchy = client.get(
            f"/ccx/service/customreport2/{TENANT}/Organization_Hierarchy",
            headers=AUTH,
        ).json()["Report_Entry"]
        structure = client.get(
            f"/ccx/service/customreport2/{TENANT}/Org_Structure",
            headers=AUTH,
        ).json()["Report_Entry"]

        assert "Organization_Name" in hierarchy[0]
        assert "Name" in structure[0]
        assert "Organization_Name" not in structure[0]

        canon_a = sorted(
            normalize_report_entries(hierarchy, entity="organizations"),
            key=lambda r: r["org_code"],
        )
        canon_b = sorted(
            normalize_report_entries(structure, entity="organizations"),
            key=lambda r: r["org_code"],
        )
        assert canon_a == canon_b
        assert {r["org_code"] for r in canon_a} == {"ENG", "PLAT"}


class TestCanonicalHelpers:
    def test_unrecognised_worker_columns_raise(self):
        with pytest.raises(ValueError, match="Unrecognised"):
            normalize_worker_entry({"foo": "bar"})

    def test_unrecognised_org_columns_raise(self):
        with pytest.raises(ValueError, match="Unrecognised"):
            normalize_organization_entry({"foo": "bar"})


class TestRateLimit:
    def test_account_wide_rate_limit_depletes(self, tight_client: TestClient):
        url = f"/ccx/service/customreport2/{TENANT}/Worker_Census"
        assert tight_client.get(url, headers=AUTH).status_code == 200
        assert tight_client.get(url, headers=AUTH).status_code == 200
        assert tight_client.get(url, headers=AUTH).status_code == 200
        limited = tight_client.get(url, headers=AUTH)
        assert limited.status_code == 429
        assert limited.json()["error"] == "request.limit.exceeded"
        assert "Retry-After" in limited.headers


class TestHealthAndFactory:
    def test_health_reports_injected_store(self, client: TestClient):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {
            "status": "ok",
            "backend": "memory",
            "vendor": "workday",
        }

    def test_create_store_requires_postgres_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("WORKDAY_DATABASE_URL", raising=False)
        monkeypatch.delenv("ZENDESK_DATABASE_URL", raising=False)
        with pytest.raises(ValueError, match="src_workday"):
            create_store()
