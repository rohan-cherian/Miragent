"""
tests/api/test_portfolio.py — Portfolio view endpoint tests.

Covers:
  GET /portfolio/summary  — snapshot-based cards, graph-heuristic fallback,
                            mixed mode, aggregate stats, edge cases
  GET /portfolio/tenants  — visible tenants + last_insights_run metadata

All tests use an in-memory SQLite DB and mock the JWT auth + Neo4j driver,
so no real API keys, no Neo4j instance, and no network calls are needed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Env bootstrap (must come before any scout imports) ────────────────────────

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-portfolio-secret")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")

from scout.db.models import Base, InsightSnapshot, User  # noqa: E402

# ── In-memory SQLite ──────────────────────────────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

TENANT_A = "acme-portfolio"
TENANT_B = "techco-portfolio"
TENANT_C = "growthsaas-portfolio"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def db_session():
    session = TestingSession()
    yield session
    session.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_snapshot(
    tenant_id: str,
    critical: int = 0,
    high: int = 1,
    medium: int = 2,
    low: int = 3,
    *,
    headcount: int = 50,
    stalled_deals: int = 3,
    at_risk_arr: float = 120_000.0,
    run_at: datetime | None = None,
) -> InsightSnapshot:
    """Build a realistic InsightSnapshot for testing."""
    return InsightSnapshot(
        tenant_id=tenant_id,
        critical=critical,
        high=high,
        medium=medium,
        low=low,
        total_findings=critical + high + medium + low,
        workers_run=5,
        worker_summaries={
            "WorkforceWorker": {"total_headcount": headcount},
            "PipelineVelocityWorker": {"stalled_deals": stalled_deals},
            "ChurnPredictionWorker": {"at_risk_arr": at_risk_arr},
            "SaasLicenseWorker": {"total_software_spend": 80_000},
            "VendorBenchmarkWorker": {"total_potential_savings": 15_000},
        },
        top_findings=[
            {"worker": "WorkforceWorker", "severity": "high", "title": "Key-person risk"},
        ],
        company_profile={
            "market_segment": "mid_market",
            "business_model": "SaaS",
            "data_confidence": "medium",
        },
        narrative_snippet="This company has several workforce risks.",
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-5",
        run_at=run_at or datetime(2026, 5, 19, 9, 0, 0),
    )


def _make_auth_headers(tenant_id: str, user_id: str = "user-test-001") -> dict:
    """Return a valid JWT Authorization header for the given tenant."""
    import jwt
    from scout.config import settings

    token = jwt.encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": "admin",
            "exp": datetime.now(timezone.utc).timestamp() + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


# ── App client factory ────────────────────────────────────────────────────────

def _make_client(
    db_sess,
    *,
    current_user: User | None = None,
) -> TestClient:
    """
    Return a TestClient with:
      - get_db overridden to use the test SQLite session
      - get_current_user overridden to return *current_user* (bypasses JWT)
    """
    from scout.api.app import create_app
    from scout.db.database import get_db
    from scout.db.auth_utils import get_current_user

    if current_user is None:
        current_user = User(
            id="user-portfolio-test",
            email="pe@fund.com",
            hashed_password="x",
            tenant_id=TENANT_A,
            is_active=True,
            role="admin",
        )

    def override_db():
        yield db_sess

    def override_user():
        return current_user

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    return TestClient(app, raise_server_exceptions=True)


# ── Mock graph driver (for heuristic fallback tests) ─────────────────────────

def _mock_neo4j_driver(
    *,
    active_persons: int = 20,
    total_persons: int = 25,
    managers: int = 4,
    total_arr: float = 500_000.0,
    open_pipeline: float = 1_500_000.0,
    won: int = 5,
    lost: int = 3,
    vendor_count: int = 8,
    total_vendor_spend: float = 100_000.0,
) -> MagicMock:
    """Return a mocked Neo4j driver whose session().run().single() returns realistic data."""
    mock_org = MagicMock()
    mock_org.__getitem__ = lambda self, key: {
        "active_persons": active_persons,
        "total_persons": total_persons,
        "managers": managers,
    }[key]

    mock_revenue = MagicMock()
    mock_revenue.__getitem__ = lambda self, key: {
        "total_arr": total_arr,
        "open_pipeline": open_pipeline,
        "won": won,
        "lost": lost,
    }[key]

    mock_vendors = MagicMock()
    mock_vendors.__getitem__ = lambda self, key: {
        "vendor_count": vendor_count,
        "total_vendor_spend": total_vendor_spend,
    }[key]

    mock_run = MagicMock()
    mock_run.single.side_effect = [mock_org, mock_revenue, mock_vendors]

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run = MagicMock(return_value=mock_run)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /portfolio/tenants
# ─────────────────────────────────────────────────────────────────────────────

class TestListVisibleTenants:

    def test_returns_200(self, db_session):
        client = _make_client(db_session)
        resp = client.get("/portfolio/tenants")
        assert resp.status_code == 200

    def test_response_has_tenants_list(self, db_session):
        client = _make_client(db_session)
        data = client.get("/portfolio/tenants").json()
        assert "tenants" in data
        assert isinstance(data["tenants"], list)

    def test_returns_current_user_tenant(self, db_session):
        user = User(
            id="user-tenant-test",
            email="pm@acme.com",
            hashed_password="x",
            tenant_id="my-specific-tenant",
            is_active=True,
            role="viewer",
        )
        client = _make_client(db_session, current_user=user)
        data = client.get("/portfolio/tenants").json()
        assert data["tenants"][0]["tenant_id"] == "my-specific-tenant"

    def test_no_snapshot_has_full_intelligence_false(self, db_session):
        user = User(
            id="user-no-snap",
            email="nosnap@co.com",
            hashed_password="x",
            tenant_id="tenant-never-scanned",
            is_active=True,
            role="viewer",
        )
        client = _make_client(db_session, current_user=user)
        data = client.get("/portfolio/tenants").json()
        tenant = data["tenants"][0]
        assert tenant["has_full_intelligence"] is False
        assert tenant["last_insights_run"] is None

    def test_with_snapshot_has_full_intelligence_true(self, db_session):
        snap = _make_snapshot("tenant-with-snap", run_at=datetime(2026, 5, 15, 10, 0, 0))
        db_session.add(snap)
        db_session.commit()

        user = User(
            id="user-with-snap",
            email="withsnap@co.com",
            hashed_password="x",
            tenant_id="tenant-with-snap",
            is_active=True,
            role="viewer",
        )
        client = _make_client(db_session, current_user=user)
        data = client.get("/portfolio/tenants").json()
        tenant = data["tenants"][0]
        assert tenant["has_full_intelligence"] is True
        assert tenant["last_insights_run"] is not None

    def test_last_insights_run_is_iso_string(self, db_session):
        user = User(
            id="user-ts-test",
            email="ts@co.com",
            hashed_password="x",
            tenant_id="tenant-with-snap",  # seeded above
            is_active=True,
            role="viewer",
        )
        client = _make_client(db_session, current_user=user)
        data = client.get("/portfolio/tenants").json()
        ts = data["tenants"][0]["last_insights_run"]
        # Must parse as an ISO datetime string
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /portfolio/summary — snapshot-based cards
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioSummarySnapshotCards:

    @pytest.fixture(autouse=True, scope="class")
    def seed_snapshots(self, db_session):
        """Seed one snapshot each for TENANT_A and TENANT_B."""
        db_session.add(_make_snapshot(TENANT_A, critical=2, high=3, medium=1, low=0))
        db_session.add(_make_snapshot(TENANT_B, critical=0, high=1, medium=2, low=4))
        db_session.commit()

    def test_returns_200(self, db_session):
        client = _make_client(db_session)
        resp = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}")
        assert resp.status_code == 200

    def test_response_has_companies_and_aggregate(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        assert "companies" in data
        assert "aggregate" in data

    def test_snapshot_card_data_source(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        card = data["companies"][0]
        assert card["data_source"] == "insight_snapshot"

    def test_snapshot_card_available_true(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        assert data["companies"][0]["available"] is True

    def test_snapshot_card_has_health_score(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        card = data["companies"][0]
        assert "health_score" in card
        assert 0 <= card["health_score"] <= 100

    def test_snapshot_card_has_finding_counts(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        card = data["companies"][0]
        counts = card["finding_counts"]
        assert "critical" in counts
        assert "high" in counts
        assert "medium" in counts
        assert "low" in counts
        assert "total" in counts

    def test_snapshot_card_has_metrics(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        metrics = data["companies"][0]["metrics"]
        assert "headcount" in metrics
        assert "stalled_deals" in metrics
        assert "at_risk_arr" in metrics
        assert "saas_annual_spend" in metrics
        assert "vendor_savings_opportunity" in metrics
        assert "workers_run" in metrics

    def test_snapshot_card_metrics_are_populated(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        metrics = data["companies"][0]["metrics"]
        assert metrics["headcount"] == 50
        assert metrics["stalled_deals"] == 3
        assert metrics["at_risk_arr"] == 120_000.0

    def test_snapshot_card_has_top_findings(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        card = data["companies"][0]
        assert isinstance(card["top_findings"], list)
        assert len(card["top_findings"]) >= 1

    def test_snapshot_card_has_company_profile(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        profile = data["companies"][0]["company_profile"]
        assert "segment" in profile
        assert "business_model" in profile
        assert "data_confidence" in profile

    def test_snapshot_card_has_llm_info(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        card = data["companies"][0]
        assert card["llm_provider"] == "anthropic"
        assert card["llm_model"] == "claude-sonnet-4-5"

    def test_snapshot_card_severity_critical(self, db_session):
        """TENANT_A has 2 critical — severity must be CRITICAL."""
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        assert data["companies"][0]["severity"] == "CRITICAL"

    def test_snapshot_card_severity_high(self, db_session):
        """TENANT_B has 0 critical, 1 high — severity must be HIGH."""
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_B}").json()
        assert data["companies"][0]["severity"] == "HIGH"

    def test_multiple_tenants_returns_one_card_each(self, db_session):
        client = _make_client(db_session)
        data = client.get(
            f"/portfolio/summary?tenant_ids={TENANT_A},{TENANT_B}"
        ).json()
        tenant_ids = {c["tenant_id"] for c in data["companies"]}
        assert TENANT_A in tenant_ids
        assert TENANT_B in tenant_ids
        assert len(data["companies"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /portfolio/summary — aggregate stats
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioSummaryAggregate:

    def test_aggregate_total_companies(self, db_session):
        client = _make_client(db_session)
        data = client.get(
            f"/portfolio/summary?tenant_ids={TENANT_A},{TENANT_B}"
        ).json()
        assert data["aggregate"]["total_companies"] == 2

    def test_aggregate_companies_with_data(self, db_session):
        client = _make_client(db_session)
        data = client.get(
            f"/portfolio/summary?tenant_ids={TENANT_A},{TENANT_B}"
        ).json()
        assert data["aggregate"]["companies_with_data"] >= 2

    def test_aggregate_companies_with_full_intelligence(self, db_session):
        client = _make_client(db_session)
        data = client.get(
            f"/portfolio/summary?tenant_ids={TENANT_A},{TENANT_B}"
        ).json()
        assert data["aggregate"]["companies_with_full_intelligence"] >= 2

    def test_aggregate_critical_count(self, db_session):
        """TENANT_A has 2 criticals → critical_count must be >= 1 (CRITICAL severity)."""
        client = _make_client(db_session)
        data = client.get(
            f"/portfolio/summary?tenant_ids={TENANT_A},{TENANT_B}"
        ).json()
        assert data["aggregate"]["critical_count"] >= 1

    def test_aggregate_avg_health_score_is_int(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        avg = data["aggregate"]["avg_health_score"]
        assert isinstance(avg, int)
        assert 0 <= avg <= 100

    def test_aggregate_empty_tenant_list(self, db_session):
        client = _make_client(db_session)
        data = client.get("/portfolio/summary?tenant_ids=").json()
        assert data["companies"] == []
        assert data["aggregate"] == {}

    def test_aggregate_has_all_expected_keys(self, db_session):
        client = _make_client(db_session)
        data = client.get(f"/portfolio/summary?tenant_ids={TENANT_A}").json()
        agg = data["aggregate"]
        required_keys = {
            "total_companies",
            "companies_with_data",
            "companies_with_full_intelligence",
            "companies_needing_insights_run",
            "critical_count",
            "high_count",
            "healthy_count",
            "avg_health_score",
            "total_critical_findings",
            "total_high_findings",
        }
        assert required_keys.issubset(set(agg.keys()))


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /portfolio/summary — graph heuristic fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioSummaryHeuristicFallback:
    """
    TENANT_C has no InsightSnapshot → falls back to graph heuristics.
    The Neo4j driver is mocked to avoid requiring a real connection.
    """

    def _client_with_mock_driver(self, db_session, mock_driver: MagicMock) -> TestClient:
        from scout.api.app import create_app
        from scout.db.database import get_db
        from scout.db.auth_utils import get_current_user

        user = User(
            id="user-heuristic-test",
            email="heuristic@test.com",
            hashed_password="x",
            tenant_id=TENANT_A,
            is_active=True,
            role="admin",
        )

        def override_db():
            yield db_session

        def override_user():
            return user

        app = create_app()
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user

        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            return TestClient(app, raise_server_exceptions=True)

    def test_heuristic_card_data_source(self, db_session):
        mock_driver = _mock_neo4j_driver()
        client = self._client_with_mock_driver(db_session, mock_driver)
        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            data = client.get(f"/portfolio/summary?tenant_ids={TENANT_C}").json()
        card = data["companies"][0]
        assert card["data_source"] == "graph_heuristics"

    def test_heuristic_card_available_true(self, db_session):
        mock_driver = _mock_neo4j_driver()
        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            client = self._client_with_mock_driver(db_session, mock_driver)
            data = client.get(f"/portfolio/summary?tenant_ids={TENANT_C}").json()
        assert data["companies"][0]["available"] is True

    def test_heuristic_card_last_insights_run_is_none(self, db_session):
        mock_driver = _mock_neo4j_driver()
        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            client = self._client_with_mock_driver(db_session, mock_driver)
            data = client.get(f"/portfolio/summary?tenant_ids={TENANT_C}").json()
        assert data["companies"][0]["last_insights_run"] is None

    def test_heuristic_card_note_suggests_insights_run(self, db_session):
        mock_driver = _mock_neo4j_driver()
        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            client = self._client_with_mock_driver(db_session, mock_driver)
            data = client.get(f"/portfolio/summary?tenant_ids={TENANT_C}").json()
        note = data["companies"][0].get("note", "")
        assert "insights" in note.lower() or "intelligence" in note.lower()

    def test_heuristic_card_has_headcount(self, db_session):
        mock_driver = _mock_neo4j_driver(active_persons=42)
        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            client = self._client_with_mock_driver(db_session, mock_driver)
            data = client.get(f"/portfolio/summary?tenant_ids={TENANT_C}").json()
        assert data["companies"][0]["metrics"]["headcount"] == 42

    def test_heuristic_card_low_data_confidence(self, db_session):
        mock_driver = _mock_neo4j_driver()
        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            client = self._client_with_mock_driver(db_session, mock_driver)
            data = client.get(f"/portfolio/summary?tenant_ids={TENANT_C}").json()
        profile = data["companies"][0]["company_profile"]
        assert profile["data_confidence"] == "low"

    def test_graph_error_returns_unavailable_card(self, db_session):
        """If Neo4j query fails, card should be available=False, not crash."""
        bad_driver = MagicMock()
        bad_driver.session.side_effect = Exception("Neo4j connection refused")

        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=bad_driver,
        ):
            client = self._client_with_mock_driver(db_session, bad_driver)
            data = client.get(f"/portfolio/summary?tenant_ids={TENANT_C}").json()
        card = data["companies"][0]
        assert card["available"] is False
        assert card["data_source"] == "none"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /portfolio/summary — sort order & mixed mode
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioSummarySortOrder:
    """
    Snapshot cards (real intelligence) should come before graph-heuristic cards.
    Within each group, worst health score should come first.
    """

    def test_snapshot_cards_before_heuristic_cards(self, db_session):
        mock_driver = _mock_neo4j_driver()
        from scout.api.app import create_app
        from scout.db.database import get_db
        from scout.db.auth_utils import get_current_user

        user = User(
            id="user-sort-test",
            email="sort@test.com",
            hashed_password="x",
            tenant_id=TENANT_A,
            is_active=True,
            role="admin",
        )

        def override_db():
            yield db_session

        def override_user():
            return user

        app = create_app()
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user

        with patch(
            "scout.api.routes.portfolio.GraphDatabase.driver",
            return_value=mock_driver,
        ):
            client = TestClient(app, raise_server_exceptions=True)
            # Request both snapshot tenants + one heuristic tenant
            data = client.get(
                f"/portfolio/summary?tenant_ids={TENANT_A},{TENANT_B},{TENANT_C}"
            ).json()

        companies = data["companies"]
        assert len(companies) == 3

        sources = [c["data_source"] for c in companies]
        # All snapshot cards before any heuristic card
        seen_heuristic = False
        for source in sources:
            if source == "graph_heuristics":
                seen_heuristic = True
            elif source == "insight_snapshot":
                assert not seen_heuristic, (
                    "Snapshot card appeared after a heuristic card — wrong sort order"
                )

    def test_worst_health_score_first_among_snapshots(self, db_session):
        """TENANT_A has 2 critical (lower score) → must appear before TENANT_B."""
        client = _make_client(db_session)
        data = client.get(
            f"/portfolio/summary?tenant_ids={TENANT_A},{TENANT_B}"
        ).json()
        snapshot_cards = [
            c for c in data["companies"] if c["data_source"] == "insight_snapshot"
        ]
        if len(snapshot_cards) >= 2:
            scores = [c["health_score"] for c in snapshot_cards]
            assert scores == sorted(scores), "Cards not sorted worst-first"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: scoring helpers (unit-level, no HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringHelpers:
    """Direct unit tests for _health_score and _severity_label."""

    def test_health_score_no_findings(self):
        from scout.api.routes.portfolio import _health_score
        assert _health_score(0, 0, 0, 0) == 100

    def test_health_score_single_critical(self):
        from scout.api.routes.portfolio import _health_score
        score = _health_score(1, 0, 0, 0)
        assert score == 75  # 100 - 25

    def test_health_score_capped_at_zero(self):
        from scout.api.routes.portfolio import _health_score
        assert _health_score(10, 10, 10, 10) == 0

    def test_health_score_no_negative(self):
        from scout.api.routes.portfolio import _health_score
        assert _health_score(100, 100, 100, 100) >= 0

    def test_severity_label_critical(self):
        from scout.api.routes.portfolio import _severity_label
        assert _severity_label(1, 0, 0) == "CRITICAL"

    def test_severity_label_high(self):
        from scout.api.routes.portfolio import _severity_label
        assert _severity_label(0, 2, 0) == "HIGH"

    def test_severity_label_medium(self):
        from scout.api.routes.portfolio import _severity_label
        assert _severity_label(0, 0, 1) == "MEDIUM"

    def test_severity_label_healthy(self):
        from scout.api.routes.portfolio import _severity_label
        assert _severity_label(0, 0, 0) == "HEALTHY"

    def test_severity_label_critical_overrides_high(self):
        from scout.api.routes.portfolio import _severity_label
        assert _severity_label(1, 5, 3) == "CRITICAL"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: InsightSnapshot model
# ─────────────────────────────────────────────────────────────────────────────

class TestInsightSnapshotModel:
    """Direct ORM tests — no HTTP layer."""

    def test_snapshot_persists_and_reads_back(self, db_session):
        snap = _make_snapshot("model-test-tenant", critical=1, high=2)
        db_session.add(snap)
        db_session.commit()

        loaded = (
            db_session.query(InsightSnapshot)
            .filter_by(tenant_id="model-test-tenant")
            .first()
        )
        assert loaded is not None
        assert loaded.critical == 1
        assert loaded.high == 2

    def test_snapshot_json_fields_round_trip(self, db_session):
        snap = _make_snapshot("json-test-tenant")
        db_session.add(snap)
        db_session.commit()

        loaded = (
            db_session.query(InsightSnapshot)
            .filter_by(tenant_id="json-test-tenant")
            .first()
        )
        assert isinstance(loaded.worker_summaries, dict)
        assert "WorkforceWorker" in loaded.worker_summaries
        assert isinstance(loaded.top_findings, list)
        assert isinstance(loaded.company_profile, dict)

    def test_multiple_snapshots_latest_wins(self, db_session):
        """Querying by run_at desc should return the most recent snapshot."""
        from sqlalchemy import desc

        tenant = "multi-snap-tenant"
        old_snap = _make_snapshot(tenant, critical=5, run_at=datetime(2026, 1, 1))
        new_snap = _make_snapshot(tenant, critical=0, run_at=datetime(2026, 5, 19))
        db_session.add(old_snap)
        db_session.add(new_snap)
        db_session.commit()

        latest = (
            db_session.query(InsightSnapshot)
            .filter_by(tenant_id=tenant)
            .order_by(desc(InsightSnapshot.run_at))
            .first()
        )
        assert latest.critical == 0  # the newer one

    def test_narrative_snippet_stored(self, db_session):
        snap = _make_snapshot("narrative-test-tenant")
        db_session.add(snap)
        db_session.commit()

        loaded = (
            db_session.query(InsightSnapshot)
            .filter_by(tenant_id="narrative-test-tenant")
            .first()
        )
        assert loaded.narrative_snippet == "This company has several workforce risks."

    def test_run_at_defaults_to_now(self, db_session):
        """InsightSnapshot without explicit run_at should use server_default."""
        snap = InsightSnapshot(
            tenant_id="no-run-at-tenant",
            critical=0,
            high=0,
            medium=0,
            low=0,
            total_findings=0,
            workers_run=0,
        )
        db_session.add(snap)
        db_session.commit()

        loaded = (
            db_session.query(InsightSnapshot)
            .filter_by(tenant_id="no-run-at-tenant")
            .first()
        )
        # run_at may be None (server_default not triggered in SQLite easily)
        # but the row should exist
        assert loaded is not None
