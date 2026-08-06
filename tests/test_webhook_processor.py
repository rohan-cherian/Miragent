"""
tests/test_webhook_processor.py — Sprint 27: Webhook Processor Tests

Validates:
  1. persist_and_process() creates a WebhookEvent row and returns action IDs
  2. Idempotency: duplicate delivery_id skips re-processing
  3. Unknown event types → status=IGNORED, no actions created
  4. Handler errors → status=FAILED, error_detail set
  5. SFDC contact.terminated → deprovision_access action created
  6. Workday worker.terminated → deprovision_access action created
  7. Workday worker.hired → send_onboarding_tasks action created
  8. NetSuite po.approved → marks matching approve_po action COMPLETE
  9. SFDC opportunity.updated → marks stalled-deal action IN_PROGRESS or COMPLETE
 10. Webhook API routes: /webhooks/generic returns 200 with correct shape
 11. Webhook API routes: /webhooks/salesforce with missing signature → 401 (when secret set)
 12. HMAC signature verification works correctly
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── DB bootstrap ──────────────────────────────────────────────────────────────

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-sprint27")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")

from sqlalchemy.pool import StaticPool  # noqa: E402

from scout.db.models import Base, RemediationAction, WebhookEvent  # noqa: E402

# StaticPool ensures all connections reuse the same in-memory SQLite connection,
# so tables created in setup_db are visible to the TestClient's sessions too.
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

TENANT = "acme-sprint27"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    session = TestingSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── FastAPI test client ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_client():
    from scout.api.app import create_app
    from scout.db.database import get_db

    def override_db():
        session = TestingSession()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


# ── WebhookProcessor unit tests ───────────────────────────────────────────────

class TestPersistAndProcess:
    """Tests for the persist_and_process() core function."""

    def test_unknown_event_type_ignored(self, db):
        from scout.actions.webhook_processor import persist_and_process

        event, action_ids = persist_and_process(
            db=db,
            source="sfdc",
            event_type="unknown.event.xyz",
            tenant_id=TENANT,
            payload={"data": "test"},
        )
        assert event.status == "IGNORED"
        assert action_ids == []
        assert event.id is not None

    def test_idempotency_skips_duplicate(self, db):
        from scout.actions.webhook_processor import persist_and_process

        idem_key = "sfdc:acme-idem:delivery-001:rec-001"

        event1, ids1 = persist_and_process(
            db=db,
            source="sfdc",
            event_type="unknown.event",
            tenant_id="acme-idem",
            payload={"Id": "rec-001"},
            idempotency_key=idem_key,
        )
        db.commit()

        event2, ids2 = persist_and_process(
            db=db,
            source="sfdc",
            event_type="unknown.event",
            tenant_id="acme-idem",
            payload={"Id": "rec-001"},
            idempotency_key=idem_key,
        )
        # Same event returned, not a new row
        assert event1.id == event2.id
        assert ids2 == []

    def test_event_row_has_correct_fields(self, db):
        from scout.actions.webhook_processor import persist_and_process

        event, _ = persist_and_process(
            db=db,
            source="workday",
            event_type="worker.hired",
            tenant_id="acme-fields-test",
            payload={"workday_id": "wd-999", "worker_name": "Alice New"},
        )
        assert event.source == "workday"
        assert event.event_type == "worker.hired"
        assert event.tenant_id == "acme-fields-test"
        assert event.status in {"DONE", "PENDING"}  # processed synchronously

    def test_handler_exception_marks_failed(self, db):
        from scout.actions import webhook_processor
        from scout.actions.webhook_processor import process_event

        event = WebhookEvent(
            tenant_id="acme-fail-test",
            source="sfdc",
            event_type="contact.terminated",
            payload={"Id": "will-cause-error"},
            status="PENDING",
        )
        db.add(event)
        db.flush()

        # Patch the dispatch table directly so the reference the processor
        # holds is actually replaced (module-level patching doesn't affect
        # already-resolved function objects in the dict)
        original_table = webhook_processor._DISPATCH_TABLE
        error_handler = MagicMock(side_effect=RuntimeError("DB connection lost"))
        patched_table = {
            "sfdc": {"contact.terminated": error_handler},
        }
        webhook_processor._DISPATCH_TABLE = patched_table
        try:
            ids = process_event(db, event)
        finally:
            webhook_processor._DISPATCH_TABLE = original_table

        assert ids == []
        assert event.status == "FAILED"
        assert "DB connection lost" in event.error_detail


class TestSfdcHandlers:
    """Tests for SFDC webhook event handlers."""

    def test_contact_terminated_creates_deprovision(self, db):
        from scout.actions.webhook_processor import persist_and_process

        event, action_ids = persist_and_process(
            db=db,
            source="sfdc",
            event_type="contact.terminated",
            tenant_id="acme-sfdc-term",
            payload={
                "Id": "003TERM001",
                "contact_id": "003TERM001",
                "Name": "Sarah Departed",
                "workday_id": "wd-sarah-001",
            },
        )
        assert event.status == "DONE"
        assert len(action_ids) >= 1

        action = db.query(RemediationAction).filter_by(
            tenant_id="acme-sfdc-term", action_type="deprovision_access"
        ).one()
        assert action.execution_payload["worker_id"] == "wd-sarah-001"
        assert action.worker_name == "WebhookProcessor"

    def test_contact_terminated_idempotent(self, db):
        from scout.actions.webhook_processor import persist_and_process

        tenant = "acme-sfdc-term-idem"
        payload = {"contact_id": "003IDEM", "Name": "Idem Person", "workday_id": "wd-idem"}

        _, ids1 = persist_and_process(
            db=db, source="sfdc", event_type="contact.terminated",
            tenant_id=tenant, payload=payload,
            idempotency_key=f"sfdc:{tenant}:del-1:003IDEM",
        )
        db.commit()
        _, ids2 = persist_and_process(
            db=db, source="sfdc", event_type="contact.terminated",
            tenant_id=tenant, payload=payload,
            idempotency_key=f"sfdc:{tenant}:del-1:003IDEM",
        )
        # Duplicate delivery → same action row, not a new one
        assert len(
            db.query(RemediationAction).filter_by(
                tenant_id=tenant, action_type="deprovision_access"
            ).all()
        ) == 1

    def test_opportunity_updated_marks_action_complete(self, db):
        """SFDC opportunity.updated with FOUND evidence marks the action COMPLETE."""
        from scout.actions.factory import ActionFactory, stalled_deal_followup
        from scout.actions.webhook_processor import persist_and_process

        tenant = "acme-opp-complete"
        opp_id = "opp-ev-001"

        # Create an existing OPEN action for this opportunity
        factory = ActionFactory(db, tenant)
        factory.emit(stalled_deal_followup(
            finding_hash=f"i2r-stalled-{tenant}-{opp_id}",
            worker_name="IssueToResolutionWorker",
            opportunity_name="Test Deal",
            opportunity_id=opp_id,
            account_id="acct-ev-001",
            days_stalled=70,
        ))
        factory.flush()
        db.commit()

        # Mock evidence checker to return FOUND
        from scout.actions.evidence_checkers import EvidenceResult, EvidenceCheckResult
        mock_checker = MagicMock()
        mock_checker.check.return_value = EvidenceCheckResult(
            result=EvidenceResult.FOUND,
            detail="Activity logged",
        )

        with patch("scout.actions.evidence_checkers.get_checker", return_value=mock_checker):
            event, action_ids = persist_and_process(
                db=db,
                source="sfdc",
                event_type="opportunity.updated",
                tenant_id=tenant,
                payload={"Id": opp_id, "opportunity_id": opp_id, "StageName": "Closed Won"},
            )
            db.commit()

        assert event.status == "DONE"
        assert len(action_ids) >= 1

        action = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="log_activity"
        ).one()
        assert action.status == "COMPLETE"
        assert action.completion_method == "WEBHOOK"


class TestWorkdayHandlers:
    """Tests for Workday webhook event handlers."""

    def test_worker_terminated_creates_deprovision(self, db):
        from scout.actions.webhook_processor import persist_and_process

        tenant = "acme-wd-term"
        event, action_ids = persist_and_process(
            db=db,
            source="workday",
            event_type="worker.terminated",
            tenant_id=tenant,
            payload={
                "worker_id": "wd-bob-term",
                "worker_name": "Bob Exiting",
                "termination_date": "2026-05-14",
            },
        )
        assert event.status == "DONE"
        assert len(action_ids) >= 1

        action = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="deprovision_access"
        ).one()
        assert action.execution_payload["worker_id"] == "wd-bob-term"
        assert "Bob Exiting" in action.title

    def test_worker_terminated_missing_worker_id_produces_no_action(self, db):
        from scout.actions.webhook_processor import persist_and_process

        event, action_ids = persist_and_process(
            db=db,
            source="workday",
            event_type="worker.terminated",
            tenant_id="acme-wd-noid",
            payload={"worker_name": "Ghost"},  # no worker_id
        )
        # Handler returns [] when no ID
        assert action_ids == []

    def test_worker_hired_creates_onboarding_action(self, db):
        from scout.actions.webhook_processor import persist_and_process

        tenant = "acme-wd-hire"
        event, action_ids = persist_and_process(
            db=db,
            source="workday",
            event_type="worker.hired",
            tenant_id=tenant,
            payload={
                "workday_id": "wd-newbie-001",
                "worker_name": "Charlie Newbie",
                "start_date": "2026-06-01",
                "manager_email": "mgr@acme.com",
            },
        )
        assert event.status == "DONE"
        assert len(action_ids) >= 1

        action = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="send_onboarding_tasks"
        ).one()
        payload = action.execution_payload
        assert payload["worker_id"] == "wd-newbie-001"
        assert payload["start_date"] == "2026-06-01"
        assert action.assigned_to_email == "mgr@acme.com"
        assert "Charlie Newbie" in action.title

    def test_worker_hired_idempotent(self, db):
        from scout.actions.webhook_processor import persist_and_process

        tenant = "acme-wd-hire-idem"
        payload = {"workday_id": "wd-idem-hire", "worker_name": "Idem Hire", "start_date": "2026-07-01"}

        _, ids1 = persist_and_process(
            db=db, source="workday", event_type="worker.hired",
            tenant_id=tenant, payload=payload,
            idempotency_key=f"workday:{tenant}:del-hire-1:wd-idem-hire",
        )
        db.commit()
        _, ids2 = persist_and_process(
            db=db, source="workday", event_type="worker.hired",
            tenant_id=tenant, payload=payload,
            idempotency_key=f"workday:{tenant}:del-hire-1:wd-idem-hire",
        )
        actions = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="send_onboarding_tasks"
        ).all()
        assert len(actions) == 1


class TestNetSuiteHandlers:
    """Tests for NetSuite webhook event handlers."""

    def test_po_approved_marks_action_complete(self, db):
        """po.approved event closes an existing open approve_po action."""
        from scout.actions.factory import ActionFactory, ActionSpec
        from scout.actions.webhook_processor import persist_and_process

        tenant = "acme-ns-po"
        po_id = "po-ns-001"

        # Pre-create an open approve_po action for this PO
        factory = ActionFactory(db, tenant)
        factory.emit(ActionSpec(
            action_type="approve_po",
            title="Approve PO for Acme Supplies",
            description="PO pending approval",
            evidence_source="netsuite",
            evidence_query_type="po_approved",
            evidence_target_ids=[po_id],
            execution_payload={"po_id": po_id},
            finding_hash=f"ns-po-{tenant}-{po_id}",
            worker_name="VendorBenchmarkWorker",
        ))
        factory.flush()
        db.commit()

        event, action_ids = persist_and_process(
            db=db,
            source="netsuite",
            event_type="po.approved",
            tenant_id=tenant,
            payload={"Id": po_id, "po_id": po_id, "status": "Approved"},
        )
        db.commit()

        assert event.status == "DONE"
        assert po_id in str(action_ids) or len(action_ids) >= 1

        action = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="approve_po"
        ).one()
        assert action.status == "COMPLETE"
        assert action.completion_method == "WEBHOOK"

    def test_contract_renewed_marks_route_action_complete(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec
        from scout.actions.webhook_processor import persist_and_process

        tenant = "acme-ns-contract"
        contract_id = "contract-ns-001"

        factory = ActionFactory(db, tenant)
        factory.emit(ActionSpec(
            action_type="route_for_approval",
            title="Route contract renewal for approval",
            description="Contract up for renewal",
            evidence_source="netsuite",
            evidence_query_type="contract_renewal_created",
            evidence_target_ids=[contract_id],
            execution_payload={"contract_id": contract_id},
            finding_hash=f"ns-contract-{tenant}-{contract_id}",
            worker_name="VendorBenchmarkWorker",
        ))
        factory.flush()
        db.commit()

        _, action_ids = persist_and_process(
            db=db,
            source="netsuite",
            event_type="contract.renewed",
            tenant_id=tenant,
            payload={"Id": contract_id, "contract_id": contract_id},
        )
        db.commit()

        action = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="route_for_approval"
        ).one()
        assert action.status == "COMPLETE"
        assert "contract-ns-001" in (action.completion_notes or "")

    def test_invoice_created_with_no_matching_action(self, db):
        """invoice.created with no matching open action returns [] gracefully."""
        from scout.actions.webhook_processor import persist_and_process

        event, action_ids = persist_and_process(
            db=db,
            source="netsuite",
            event_type="invoice.created",
            tenant_id="acme-ns-no-action",
            payload={"Id": "inv-no-match", "vendor_id": "vendor-xyz"},
        )
        assert event.status == "DONE"
        assert action_ids == []


class TestProcessEventStatuses:
    """Tests for WebhookEvent status transitions in process_event."""

    def test_already_done_event_is_skipped(self, db):
        from scout.actions.webhook_processor import process_event

        event = WebhookEvent(
            tenant_id="acme-skip-test",
            source="sfdc",
            event_type="contact.terminated",
            payload={"Id": "already-done"},
            status="DONE",
        )
        db.add(event)
        db.flush()

        ids = process_event(db, event)
        assert ids == []
        assert event.status == "DONE"  # unchanged

    def test_failed_event_is_skipped_on_reprocess(self, db):
        from scout.actions.webhook_processor import process_event

        event = WebhookEvent(
            tenant_id="acme-failed-skip",
            source="workday",
            event_type="worker.terminated",
            payload={"worker_id": "wd-failed"},
            status="FAILED",
            error_detail="Previous error",
        )
        db.add(event)
        db.flush()

        ids = process_event(db, event)
        assert ids == []


# ── Webhook API route tests ────────────────────────────────────────────────────

class TestWebhookAPIRoutes:
    """Tests for the FastAPI webhook endpoints via the test client."""

    def test_generic_webhook_returns_200(self, app_client):
        resp = app_client.post(
            "/webhooks/generic",
            json={
                "source": "workday",
                "event_type": "worker.hired",
                "tenant_id": "acme-api-test",
                "records": [
                    {
                        "workday_id": "wd-api-001",
                        "worker_name": "API Test Hire",
                        "start_date": "2026-06-15",
                        "manager_email": "boss@acme.com",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["received"] is True
        assert data["record_count"] == 1
        assert data["event_type"] == "worker.hired"
        assert "event_id" in data

    def test_generic_webhook_unknown_event_ignored(self, app_client):
        resp = app_client.post(
            "/webhooks/generic",
            json={
                "source": "sfdc",
                "event_type": "completely.unknown.event",
                "tenant_id": "acme-api-ignore",
                "records": [{"Id": "rec-001"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["received"] is True
        assert data["actions_triggered"] == 0

    def test_salesforce_webhook_no_secret_accepts_request(self, app_client):
        """When SALESFORCE_WEBHOOK_SECRET is not set, request is accepted."""
        # Ensure secret is unset
        os.environ.pop("SALESFORCE_WEBHOOK_SECRET", None)

        resp = app_client.post(
            "/webhooks/salesforce",
            json={
                "source": "sfdc",
                "event_type": "contact.terminated",
                "tenant_id": "acme-sfdc-nosecret",
                "records": [
                    {
                        "Id": "003NOSECRET",
                        "contact_id": "003NOSECRET",
                        "Name": "Test Contact",
                        "workday_id": "wd-nosecret",
                    }
                ],
            },
        )
        assert resp.status_code == 200

    def test_salesforce_webhook_with_secret_missing_header_returns_401(self, app_client):
        """When secret is set and header is missing, endpoint returns 401."""
        os.environ["SALESFORCE_WEBHOOK_SECRET"] = "super-secret"

        try:
            resp = app_client.post(
                "/webhooks/salesforce",
                json={
                    "source": "sfdc",
                    "event_type": "contact.terminated",
                    "tenant_id": "acme-401-test",
                    "records": [{"Id": "003SEC"}],
                },
                # No X-Salesforce-Signature header
            )
            assert resp.status_code == 401
            assert "signature" in resp.json()["detail"].lower()
        finally:
            del os.environ["SALESFORCE_WEBHOOK_SECRET"]

    def test_workday_webhook_returns_200(self, app_client):
        resp = app_client.post(
            "/webhooks/workday",
            json={
                "source": "workday",
                "event_type": "worker.terminated",
                "tenant_id": "acme-wd-api",
                "records": [
                    {
                        "worker_id": "wd-api-term-001",
                        "worker_name": "Departed Worker",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["received"] is True
        assert data["actions_triggered"] >= 1

    def test_netsuite_webhook_returns_200(self, app_client):
        resp = app_client.post(
            "/webhooks/netsuite",
            json={
                "source": "netsuite",
                "event_type": "po.approved",
                "tenant_id": "acme-ns-api",
                "records": [{"Id": "po-api-no-match", "po_id": "po-api-no-match"}],
            },
        )
        assert resp.status_code == 200

    def test_multiple_records_processed_independently(self, app_client):
        resp = app_client.post(
            "/webhooks/workday",
            json={
                "source": "workday",
                "event_type": "worker.terminated",
                "tenant_id": "acme-multi-term",
                "records": [
                    {"worker_id": "wd-multi-001", "worker_name": "Person One"},
                    {"worker_id": "wd-multi-002", "worker_name": "Person Two"},
                    {"worker_id": "wd-multi-003", "worker_name": "Person Three"},
                ],
                "delivery_id": "batch-delivery-001",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["record_count"] == 3
        assert data["actions_triggered"] >= 3


# ── HMAC signature verification unit tests ─────────────────────────────────────

class TestHMACVerification:
    """Tests for _verify_hmac signature validation."""

    def test_valid_signature_accepted(self):
        from scout.api.routes.webhooks import _verify_hmac

        secret = "my-webhook-secret"
        body = b'{"event": "test"}'
        sig = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()

        assert _verify_hmac(secret, body, sig) is True

    def test_invalid_signature_rejected(self):
        from scout.api.routes.webhooks import _verify_hmac

        assert _verify_hmac("secret", b"body", "badhex") is False

    def test_sha256_prefix_stripped(self):
        from scout.api.routes.webhooks import _verify_hmac

        secret = "prefix-secret"
        body = b"payload"
        raw_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        prefixed_sig = f"sha256={raw_sig}"

        assert _verify_hmac(secret, body, prefixed_sig) is True

    def test_wrong_secret_rejected(self):
        from scout.api.routes.webhooks import _verify_hmac

        body = b"test body"
        sig = hmac.new(b"correct-secret", body, hashlib.sha256).hexdigest()
        assert _verify_hmac("wrong-secret", body, sig) is False

    def test_tampered_body_rejected(self):
        from scout.api.routes.webhooks import _verify_hmac

        secret = "the-secret"
        original = b"original body"
        sig = hmac.new(secret.encode(), original, hashlib.sha256).hexdigest()
        # Attacker modifies the body
        assert _verify_hmac(secret, b"tampered body", sig) is False
