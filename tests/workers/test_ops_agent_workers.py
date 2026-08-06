"""Tests for Sprint 10 Ops Agent Workers."""

import time
import pytest
from fastapi.testclient import TestClient
from scout.api.app import create_app
from scout.workers.base import Severity


@pytest.fixture(scope="module")
def seeded_driver():
    from neo4j import GraphDatabase
    from scout.config import settings

    app = create_app()
    client = TestClient(app)

    post = client.post("/scans", json={"tenant_id": "ops-test"})
    scan_id = post.json()["scan_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        data = client.get(f"/scans/{scan_id}").json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert data["status"] == "completed", f"Scan failed: {data}"

    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    yield driver
    driver.close()


# ─────────────────────────────────────────────────────────────────────────────
class TestOnboardingWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.onboarding import OnboardingWorker
        assert OnboardingWorker(seeded_driver).run("ops-test").worker_name == "OnboardingWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.onboarding import OnboardingWorker
        assert OnboardingWorker(seeded_driver).run("ops-test").error is None

    def test_summary_has_onboarding_metrics(self, seeded_driver):
        from scout.workers.onboarding import OnboardingWorker
        stats = OnboardingWorker(seeded_driver).run("ops-test").summary_stats
        assert "unowned_accounts" in stats
        assert "unassigned_deals" in stats
        assert "checklist_templates_generated" in stats

    def test_has_findings(self, seeded_driver):
        from scout.workers.onboarding import OnboardingWorker
        assert len(OnboardingWorker(seeded_driver).run("ops-test").findings) >= 1

    def test_checklist_finding_has_items(self, seeded_driver):
        from scout.workers.onboarding import OnboardingWorker
        result = OnboardingWorker(seeded_driver).run("ops-test")
        for f in result.findings:
            checklist = f.data.get("checklist")
            if checklist is not None:
                assert isinstance(checklist, list)
                assert len(checklist) >= 1

    def test_findings_have_valid_severity(self, seeded_driver):
        from scout.workers.onboarding import OnboardingWorker
        for f in OnboardingWorker(seeded_driver).run("ops-test").findings:
            assert f.severity in set(Severity)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.onboarding import OnboardingWorker
        json.dumps(OnboardingWorker(seeded_driver).run("ops-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestOffboardingWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.offboarding import OffboardingWorker
        assert OffboardingWorker(seeded_driver).run("ops-test").worker_name == "OffboardingWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.offboarding import OffboardingWorker
        assert OffboardingWorker(seeded_driver).run("ops-test").error is None

    def test_summary_has_offboarding_metrics(self, seeded_driver):
        from scout.workers.offboarding import OffboardingWorker
        stats = OffboardingWorker(seeded_driver).run("ops-test").summary_stats
        assert "inactive_persons" in stats
        assert "accounts_at_risk" in stats
        assert "deals_at_risk" in stats
        assert "total_arr_at_risk" in stats

    def test_counts_non_negative(self, seeded_driver):
        from scout.workers.offboarding import OffboardingWorker
        stats = OffboardingWorker(seeded_driver).run("ops-test").summary_stats
        assert stats.get("inactive_persons", 0) >= 0
        assert stats.get("total_arr_at_risk", 0) >= 0

    def test_has_findings(self, seeded_driver):
        from scout.workers.offboarding import OffboardingWorker
        assert len(OffboardingWorker(seeded_driver).run("ops-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.offboarding import OffboardingWorker
        json.dumps(OffboardingWorker(seeded_driver).run("ops-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestAPProcessingWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.ap_processing import APProcessingWorker
        assert APProcessingWorker(seeded_driver).run("ops-test").worker_name == "APProcessingWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.ap_processing import APProcessingWorker
        assert APProcessingWorker(seeded_driver).run("ops-test").error is None

    def test_summary_has_ap_metrics(self, seeded_driver):
        from scout.workers.ap_processing import APProcessingWorker
        stats = APProcessingWorker(seeded_driver).run("ops-test").summary_stats
        assert "total_vendors" in stats
        assert "total_annual_spend" in stats
        assert "early_pay_savings_opportunity" in stats

    def test_spend_non_negative(self, seeded_driver):
        from scout.workers.ap_processing import APProcessingWorker
        stats = APProcessingWorker(seeded_driver).run("ops-test").summary_stats
        assert stats.get("total_annual_spend", 0) >= 0
        assert stats.get("early_pay_savings_opportunity", 0) >= 0

    def test_has_findings(self, seeded_driver):
        from scout.workers.ap_processing import APProcessingWorker
        assert len(APProcessingWorker(seeded_driver).run("ops-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.ap_processing import APProcessingWorker
        json.dumps(APProcessingWorker(seeded_driver).run("ops-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestLicenseManagementWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.license_management import LicenseManagementWorker
        assert LicenseManagementWorker(seeded_driver).run("ops-test").worker_name == "LicenseManagementWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.license_management import LicenseManagementWorker
        assert LicenseManagementWorker(seeded_driver).run("ops-test").error is None

    def test_summary_has_license_metrics(self, seeded_driver):
        from scout.workers.license_management import LicenseManagementWorker
        stats = LicenseManagementWorker(seeded_driver).run("ops-test").summary_stats
        assert "total_licenses" in stats
        assert "critical_renewals" in stats
        assert "upcoming_renewals" in stats

    def test_renewal_counts_non_negative(self, seeded_driver):
        from scout.workers.license_management import LicenseManagementWorker
        stats = LicenseManagementWorker(seeded_driver).run("ops-test").summary_stats
        assert stats.get("critical_renewals", 0) >= 0
        assert stats.get("upcoming_renewals", 0) >= 0

    def test_has_findings(self, seeded_driver):
        from scout.workers.license_management import LicenseManagementWorker
        assert len(LicenseManagementWorker(seeded_driver).run("ops-test").findings) >= 1

    def test_findings_have_valid_severity(self, seeded_driver):
        from scout.workers.license_management import LicenseManagementWorker
        for f in LicenseManagementWorker(seeded_driver).run("ops-test").findings:
            assert f.severity in set(Severity)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.license_management import LicenseManagementWorker
        json.dumps(LicenseManagementWorker(seeded_driver).run("ops-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestExpenseAuditWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.expense_audit import ExpenseAuditWorker
        assert ExpenseAuditWorker(seeded_driver).run("ops-test").worker_name == "ExpenseAuditWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.expense_audit import ExpenseAuditWorker
        assert ExpenseAuditWorker(seeded_driver).run("ops-test").error is None

    def test_summary_has_audit_metrics(self, seeded_driver):
        from scout.workers.expense_audit import ExpenseAuditWorker
        stats = ExpenseAuditWorker(seeded_driver).run("ops-test").summary_stats
        assert "total_vendors" in stats
        assert "total_spend_audited" in stats
        assert "audit_coverage_pct" in stats

    def test_audit_coverage_is_percentage(self, seeded_driver):
        from scout.workers.expense_audit import ExpenseAuditWorker
        stats = ExpenseAuditWorker(seeded_driver).run("ops-test").summary_stats
        assert 0 <= stats.get("audit_coverage_pct", 0) <= 100

    def test_has_findings(self, seeded_driver):
        from scout.workers.expense_audit import ExpenseAuditWorker
        assert len(ExpenseAuditWorker(seeded_driver).run("ops-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.expense_audit import ExpenseAuditWorker
        json.dumps(ExpenseAuditWorker(seeded_driver).run("ops-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestInsightsEndpointWith31Workers:
    """GET /insights now runs all 31 workers."""

    def test_all_sprint10_workers_present(self):
        from fastapi.testclient import TestClient
        from scout.api.app import create_app

        app = create_app()
        client = TestClient(app)

        post = client.post("/scans", json={"tenant_id": "insights-s10-test"})
        scan_id = post.json()["scan_id"]
        deadline = time.time() + 45
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert data["status"] == "completed"

        resp = client.get("/insights", params={"tenant_id": "insights-s10-test"})
        assert resp.status_code == 200
        body = resp.json()

        workers_in_response = [w["worker"] for w in body["structured"].get("workers", [])]
        for expected in [
            "OnboardingWorker", "OffboardingWorker",
            "APProcessingWorker", "LicenseManagementWorker", "ExpenseAuditWorker",
        ]:
            assert expected in workers_in_response, f"{expected} missing from /insights"

        assert len(workers_in_response) == 36, (
            f"Expected 36 workers, got {len(workers_in_response)}: {workers_in_response}"
        )
