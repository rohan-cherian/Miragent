"""
Task 24, Part B — tests for the connections and runs routes.

Three-tier skip logic, consistent with how this repo treats every
Rohan-blocked dependency:
* no live database             -> skip everything
* raw_ingest.runs / connector_registry absent (Task 6 not landed)
                               -> the blocked routes get ONE clearly-worded
                                  skip each, never a hard failure
* raw_ingest.quarantine        -> real (Task 16); its route is tested for real
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.api.app import app
from scout.canonical.models import Quarantine
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))

client = TestClient(app)


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping connections/runs-route tests")
    return engine


def _table_exists(engine, schema: str, table: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT to_regclass(:qualified)"), {"qualified": f"{schema}.{table}"}
            ).scalar()
        )


def _skip_unless(engine, schema: str, table: str) -> None:
    if not _table_exists(engine, schema, table):
        pytest.skip(
            f"{schema}.{table} does not exist yet (Task 6, Rohan's side) — "
            "route is implemented against the contract and will work once the "
            "table lands; skipping, not failing, per the project's "
            "Rohan-blocked-dependency convention"
        )


def test_list_connections_shape_when_registry_exists():
    engine = _make_engine()
    _skip_unless(engine, "raw_ingest", "connector_registry")

    response = client.get("/api/v1/connections")
    assert response.status_code == 200
    for row in response.json():
        assert set(row) >= {"id", "source_system", "status"}
        assert row["status"] in ("connected", "disconnected", "error")


def test_list_and_get_runs_shape_when_runs_table_exists():
    engine = _make_engine()
    _skip_unless(engine, "raw_ingest", "runs")

    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    rows = response.json()
    for row in rows:
        assert set(row) >= {"id", "source_system", "status", "started_at"}

    if rows:
        detail = client.get(f"/api/v1/runs/{rows[0]['id']}")
        assert detail.status_code == 200
        assert detail.json()["id"] == rows[0]["id"]

    missing = client.get(f"/api/v1/runs/{uuid.uuid4()}")
    assert missing.status_code == 404  # contract-defined 404


def test_run_quarantine_route_works_against_the_real_table():
    """raw_ingest.quarantine is Task 16's real table — no Task 6 dependency."""
    engine = _make_engine()
    run_id = uuid.uuid4()
    row_id = uuid.uuid4()
    now = datetime.now(UTC)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                Quarantine(
                    id=row_id,
                    object_path=None,
                    error_code="GM-ERR-1021",
                    error_reason="invalid email format (api smoke fixture)",
                    retry_count=0,
                    max_retries=5,
                    status="pending",
                    first_seen_at=now,
                    last_attempt_at=None,
                    tenant_id=TENANT_ID,
                    source_system="gmail",
                    external_id="api-smoke-fixture",
                    is_synthetic=True,
                    connector_run_id=run_id,
                    observed_at=now,
                    valid_from=now,
                )
            )
            session.commit()

        response = client.get(f"/api/v1/runs/{run_id}/quarantine")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["error_code"] == "GM-ERR-1021"
        assert rows[0]["status"] == "pending"

        empty = client.get(f"/api/v1/runs/{uuid.uuid4()}/quarantine")
        assert empty.status_code == 200 and empty.json() == []
    finally:
        with Session(engine) as session:
            row = session.get(Quarantine, row_id)
            if row is not None:
                session.delete(row)
                session.commit()
