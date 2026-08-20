"""
Task 24, Part D — tests for the context-pack, triage and audit routes.

Skip tiers, consistent with the whole suite:
* triage + audit tests need only Postgres.
* the context-pack test additionally needs Qdrant, and stubs embed_query
  with a deterministic pseudo-vector (the precedent tests/context/
  test_pack.py and test_kb_index.py established) so no OpenAI key is
  needed — retrieval, trust filtering and compilation all run for real.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.api.app import app
from scout.canonical.models import Case, Message, TriageResult
from scout.config import settings
from scout.governance import audit as audit_module

TENANT_ID = uuid.UUID(str(settings.tenant_id))

client = TestClient(app)


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping Part D route tests")
    return engine


def _provenance(now: datetime) -> dict:
    return {
        "tenant_id": TENANT_ID,
        "source_system": "test",
        "is_synthetic": True,
        "connector_run_id": uuid.uuid4(),
        "observed_at": now,
        "valid_from": now,
    }


def _make_case_with_message(session: Session, subject: str, body: str) -> Case:
    now = datetime.now(UTC)
    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject=subject,
        status="open",
        opened_at=now,
        **_provenance(now),
    )
    session.add(case)
    session.flush()
    session.add(
        Message(
            id=uuid.uuid4(),
            case_id=case.id,
            person_id=None,
            direction="inbound",
            channel="email",
            subject=subject,
            body_redacted=body,
            pii_map=None,
            pii_status="clean",
            src_message_id=f"api-test-{uuid.uuid4().hex[:10]}",
            thread_id=None,
            sent_at=now,
            **_provenance(now),
        )
    )
    session.flush()
    return case


def _cleanup(engine, case_ids: list[uuid.UUID]) -> None:
    with Session(engine) as session:
        for model in (TriageResult, Message):
            for row in session.query(model).filter(model.case_id.in_(case_ids)).all():
                session.delete(row)
        for row in session.query(Case).filter(Case.id.in_(case_ids)).all():
            session.delete(row)
        session.commit()


# ── Triage ────────────────────────────────────────────────────────────────


def test_triage_route_returns_latest_persisted_result_in_contract_shape():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case_with_message(session, "Licence key invalid", "Key rejected.")
            case_ids.append(case.id)
            now = datetime.now(UTC)
            for version, (confidence, band, tier) in enumerate(
                [(0.52, "low", "fast"), (0.91, "high", "standard")], start=1
            ):
                session.add(
                    TriageResult(
                        id=uuid.uuid4(),
                        case_id=case.id,
                        message_id=uuid.uuid4(),
                        intent_class="activation_failure",
                        category="licensing/activation",
                        priority="high",
                        confidence=confidence,
                        band=band,
                        rationale='Customer writes "Key rejected."',
                        model_name="test-model",
                        prompt_version="triage_v1",
                        tier_used=tier,
                        version=version,
                        **_provenance(now),
                    )
                )
            session.commit()

        response = client.get(f"/api/v1/cases/{case.id}/triage")
        assert response.status_code == 200, response.text
        body = response.json()
        # TriageResult, contract-exact required fields
        assert set(body) >= {"case_id", "band", "confidence", "reasons", "citations", "generated_at"}
        assert body["band"] == "high", "version 2 (the escalation) is the current result"
        assert body["confidence"] == pytest.approx(0.91)
        assert body["reasons"] == ['Customer writes "Key rejected."']
        assert body["citations"] == []

        missing = client.get(f"/api/v1/cases/{uuid.uuid4()}/triage")
        assert missing.status_code == 404
    finally:
        _cleanup(engine, case_ids)


# ── Audit ─────────────────────────────────────────────────────────────────


def test_audit_routes_return_contract_shaped_entries():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case_with_message(session, "Audit test", "Body.")
            case_ids.append(case.id)
            session.commit()

        audit_module.write(
            actor="part-d-test",
            action="case_correlation",
            category="scan",
            case_id=case.id,
            outputs={"reason": "new_case"},
        )
        audit_module.write(
            actor="part-d-test",
            action="intent_classification",
            category="system",
            case_id=case.id,
            confidence=0.91,
        )

        timeline = client.get(f"/api/v1/audit/{case.id}/timeline")
        assert timeline.status_code == 200
        entries = timeline.json()
        assert [entry["action"] for entry in entries] == [
            "case_correlation",
            "intent_classification",
        ], "timeline is oldest-first"
        first = entries[0]
        # AuditEntry, contract-exact required fields
        assert set(first) >= {"id", "actor", "action", "target_id", "at"}
        assert first["target_id"] == str(case.id)
        assert first["details"]["category"] == "scan"
        assert first["details"]["outputs"] == {"reason": "new_case"}

        filtered = client.get("/api/v1/audit", params={"target_id": str(case.id)})
        assert filtered.status_code == 200
        assert len(filtered.json()) == 2

        bad_filter = client.get("/api/v1/audit", params={"target_id": "not-a-uuid"})
        assert bad_filter.status_code == 422
    finally:
        _cleanup(engine, case_ids)
        # audit rows are append-only by design — deliberately not deleted


# ── Context pack (needs Qdrant; embed_query stubbed per test_pack.py) ─────


def _skip_if_qdrant_unreachable() -> None:
    try:
        from qdrant_client import QdrantClient

        QdrantClient(url=settings.qdrant_url).get_collections()
    except Exception:
        pytest.skip(f"Qdrant not reachable at {settings.qdrant_url} — skipping context-pack route test")


def _vector(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(settings.embed_dims)]


def test_context_pack_route_returns_contract_shape(monkeypatch):
    engine = _make_engine()
    _skip_if_qdrant_unreachable()

    from scout.context import retrieve as retrieve_module
    from scout.context.chunk import Chunk
    from scout.context.embed import EmbeddedChunk, upsert_chunks

    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case_with_message(
                session, "Licence key invalid", "The key returns INVALID_LICENSE_KEY."
            )
            case_ids.append(case.id)
            session.commit()

        # One chunk bound to this case, near the (stubbed) query vector.
        seed = 4242
        message_id = uuid.uuid4()
        chunk = Chunk(
            chunk_id=uuid.uuid4(),
            message_id=message_id,
            child_text="The key returns INVALID_LICENSE_KEY after renewal.",
            parent_text="The key returns INVALID_LICENSE_KEY after renewal.",
            start_offset=0,
            end_offset=50,
            case_id=case.id,
            person_id=None,
            tenant_id=TENANT_ID,
            acl_tags=[f"tenant:{TENANT_ID}"],
        )
        upsert_chunks(
            [
                EmbeddedChunk(
                    chunk=chunk,
                    embedding=_vector(seed),
                    embedded_text=chunk.child_text,
                    model="test-model",
                    dims=settings.embed_dims,
                )
            ]
        )
        monkeypatch.setattr(retrieve_module, "embed_query", lambda text: _vector(seed))

        response = client.get(f"/api/v1/cases/{case.id}/context-pack")
        assert response.status_code == 200, response.text
        body = response.json()
        # ContextPack, contract-exact required fields
        assert set(body) >= {"case_id", "summary", "citations", "trust_filtered", "generated_at"}
        assert body["case_id"] == str(case.id)
        assert body["low_context"] is False
        assert body["citations"], "the indexed chunk must surface as a citation"
        citation = body["citations"][0]
        assert set(citation) >= {
            "source_system", "source_type", "object_id", "excerpt",
            "source_ts", "deep_link", "access_status",
        }

        missing = client.get(f"/api/v1/cases/{uuid.uuid4()}/context-pack")
        assert missing.status_code == 404
    finally:
        _cleanup(engine, case_ids)
