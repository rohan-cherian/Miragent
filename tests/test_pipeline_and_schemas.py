"""
tests/test_pipeline_and_schemas.py — Sprint 44: Final coverage sprint

Covers three modules that had no direct test imports:

  scout/ingestion/pipeline.py:
    - PipelineResult dataclass: field defaults, accumulation, errors list
    - PipelineResult.print_summary(): output format and no crash guarantee
    - IngestionPipeline cannot be instantiated without Neo4j (requires DB),
      so only the dataclass layer is tested here.

  scout/graph/writer.py:
    - WriteStats dataclass: field defaults
    - WriteStats.total_nodes: sum of persons + vendors + accounts + opps
    - WriteStats.total_relationships: sum of all edge counts
    - WriteStats.summary(): returns a formatted string with key stats
    - GraphWriter requires a live Neo4j driver — not tested here.

  scout/db/schemas.py:
    - Pydantic schema instantiation and field validation
    - TenantCreate, TenantRead, UserCreate, UserRead, UserLogin
    - TokenResponse, ApiKeyCreate, ApiKeyRead, ApiKeyCreateResponse
    - model_config from_attributes=True enables ORM mode

All tests run with NO external dependencies.
"""

import io
import sys
from datetime import datetime, timezone

import pytest

from scout.graph.writer import WriteStats
from scout.ingestion.pipeline import PipelineResult


# ─────────────────────────────────────────────────────────────────────────────
# PipelineResult DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineResult:

    def test_default_construction(self):
        result = PipelineResult(tenant_id="acme-corp")
        assert result.tenant_id == "acme-corp"

    def test_default_connectors_run_is_empty(self):
        result = PipelineResult(tenant_id="t")
        assert result.connectors_run == []

    def test_default_records_extracted_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.records_extracted == 0

    def test_default_records_normalized_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.records_normalized == 0

    def test_default_records_skipped_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.records_skipped == 0

    def test_default_write_stats_is_none(self):
        result = PipelineResult(tenant_id="t")
        assert result.write_stats is None

    def test_default_persons_resolved_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.persons_resolved == 0

    def test_default_vendors_resolved_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.vendors_resolved == 0

    def test_default_accounts_resolved_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.accounts_resolved == 0

    def test_default_opportunities_resolved_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.opportunities_resolved == 0

    def test_default_duration_is_zero(self):
        result = PipelineResult(tenant_id="t")
        assert result.duration_seconds == 0.0

    def test_default_errors_is_empty(self):
        result = PipelineResult(tenant_id="t")
        assert result.errors == []

    def test_errors_list_is_mutable(self):
        result = PipelineResult(tenant_id="t")
        result.errors.append("connector failed")
        assert len(result.errors) == 1
        assert result.errors[0] == "connector failed"

    def test_connectors_run_is_mutable(self):
        result = PipelineResult(tenant_id="t")
        result.connectors_run.append("salesforce")
        result.connectors_run.append("workday")
        assert result.connectors_run == ["salesforce", "workday"]

    def test_field_assignment(self):
        result = PipelineResult(tenant_id="acme-corp")
        result.records_extracted = 500
        result.records_normalized = 480
        result.records_skipped = 20
        result.persons_resolved = 120
        result.vendors_resolved = 40
        result.duration_seconds = 5.3
        assert result.records_extracted == 500
        assert result.records_normalized == 480
        assert result.records_skipped == 20
        assert result.persons_resolved == 120
        assert result.vendors_resolved == 40
        assert result.duration_seconds == 5.3

    def test_errors_list_independent_per_instance(self):
        """Default mutable lists must not be shared between instances."""
        r1 = PipelineResult(tenant_id="t1")
        r2 = PipelineResult(tenant_id="t2")
        r1.errors.append("r1 error")
        assert r2.errors == []

    def test_connectors_list_independent_per_instance(self):
        r1 = PipelineResult(tenant_id="t1")
        r2 = PipelineResult(tenant_id="t2")
        r1.connectors_run.append("salesforce")
        assert r2.connectors_run == []


class TestPipelineResultPrintSummary:

    def _capture_summary(self, result: PipelineResult) -> str:
        """Capture stdout from print_summary()."""
        captured = io.StringIO()
        sys.stdout = captured
        try:
            result.print_summary()
        finally:
            sys.stdout = sys.__stdout__
        return captured.getvalue()

    def test_print_summary_does_not_raise(self):
        result = PipelineResult(tenant_id="acme-corp")
        result.records_extracted = 100
        result.connectors_run = ["salesforce"]
        self._capture_summary(result)  # no exception

    def test_print_summary_contains_tenant_id(self):
        result = PipelineResult(tenant_id="pinnacle-partners")
        output = self._capture_summary(result)
        assert "pinnacle-partners" in output

    def test_print_summary_contains_duration(self):
        result = PipelineResult(tenant_id="t")
        result.duration_seconds = 7.5
        output = self._capture_summary(result)
        assert "7.5" in output

    def test_print_summary_contains_extracted_count(self):
        result = PipelineResult(tenant_id="t")
        result.records_extracted = 999
        output = self._capture_summary(result)
        assert "999" in output

    def test_print_summary_with_errors_shows_error(self):
        result = PipelineResult(tenant_id="t")
        result.errors.append("Neo4j connection refused")
        output = self._capture_summary(result)
        assert "Neo4j connection refused" in output

    def test_print_summary_with_write_stats(self):
        result = PipelineResult(tenant_id="t")
        result.write_stats = WriteStats(persons_merged=50, vendors_merged=20)
        output = self._capture_summary(result)
        assert "50" in output

    def test_print_summary_no_errors_section_when_clean(self):
        result = PipelineResult(tenant_id="t")
        result.errors = []
        output = self._capture_summary(result)
        assert "ERRORS" not in output

    def test_print_summary_with_connectors_list(self):
        result = PipelineResult(tenant_id="t")
        result.connectors_run = ["salesforce", "workday", "netsuite"]
        output = self._capture_summary(result)
        assert "salesforce" in output


# ─────────────────────────────────────────────────────────────────────────────
# WriteStats DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteStats:

    def test_default_all_zero(self):
        stats = WriteStats()
        assert stats.persons_merged == 0
        assert stats.vendors_merged == 0
        assert stats.accounts_merged == 0
        assert stats.opportunities_merged == 0
        assert stats.manages_relationships == 0
        assert stats.owns_relationships == 0
        assert stats.owns_deal_relationships == 0
        assert stats.in_account_relationships == 0

    def test_total_nodes_is_sum_of_entity_counts(self):
        stats = WriteStats(
            persons_merged=10,
            vendors_merged=5,
            accounts_merged=8,
            opportunities_merged=3,
        )
        assert stats.total_nodes == 26

    def test_total_nodes_all_zeros(self):
        assert WriteStats().total_nodes == 0

    def test_total_nodes_only_persons(self):
        stats = WriteStats(persons_merged=42)
        assert stats.total_nodes == 42

    def test_total_relationships_is_sum_of_edge_counts(self):
        stats = WriteStats(
            manages_relationships=15,
            owns_relationships=8,
            owns_deal_relationships=12,
            in_account_relationships=7,
        )
        assert stats.total_relationships == 42

    def test_total_relationships_all_zeros(self):
        assert WriteStats().total_relationships == 0

    def test_total_relationships_only_manages(self):
        stats = WriteStats(manages_relationships=30)
        assert stats.total_relationships == 30

    def test_summary_returns_string(self):
        stats = WriteStats(persons_merged=5, vendors_merged=3, manages_relationships=4)
        result = stats.summary()
        assert isinstance(result, str)

    def test_summary_contains_person_count(self):
        stats = WriteStats(persons_merged=77)
        assert "77" in stats.summary()

    def test_summary_contains_vendor_count(self):
        stats = WriteStats(vendors_merged=22)
        assert "22" in stats.summary()

    def test_summary_contains_manages_count(self):
        stats = WriteStats(manages_relationships=19)
        assert "19" in stats.summary()

    def test_summary_not_empty(self):
        assert WriteStats().summary() != ""

    def test_field_assignment(self):
        stats = WriteStats()
        stats.persons_merged = 100
        stats.vendors_merged = 50
        stats.manages_relationships = 80
        assert stats.total_nodes >= 150
        assert stats.manages_relationships == 80


# ─────────────────────────────────────────────────────────────────────────────
# db/schemas.py — Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class TestTenantSchemas:

    def test_tenant_create_requires_name_and_slug(self):
        from scout.db.schemas import TenantCreate
        t = TenantCreate(name="Acme Corp", slug="acme-corp")
        assert t.name == "Acme Corp"
        assert t.slug == "acme-corp"

    def test_tenant_create_missing_field_raises(self):
        from scout.db.schemas import TenantCreate
        with pytest.raises(Exception):
            TenantCreate(name="only name")  # missing slug

    def test_tenant_read_fields(self):
        from scout.db.schemas import TenantRead
        t = TenantRead(
            id="t-001",
            name="Acme Corp",
            slug="acme-corp",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        assert t.id == "t-001"
        assert t.slug == "acme-corp"
        assert t.is_active is True

    def test_tenant_read_model_config_from_attributes(self):
        from scout.db.schemas import TenantRead
        config = TenantRead.model_config
        assert config.get("from_attributes") is True


class TestUserSchemas:

    def test_user_create_fields(self):
        from scout.db.schemas import UserCreate
        u = UserCreate(
            email="alice@acme.com",
            password="secret123",
            tenant_slug="acme-corp",
        )
        assert u.email == "alice@acme.com"
        assert u.tenant_slug == "acme-corp"
        assert u.role == "viewer"  # default

    def test_user_create_custom_role(self):
        from scout.db.schemas import UserCreate
        u = UserCreate(
            email="admin@acme.com",
            password="pass",
            tenant_slug="acme",
            role="admin",
        )
        assert u.role == "admin"

    def test_user_create_validates_email_format(self):
        from scout.db.schemas import UserCreate
        with pytest.raises(Exception):
            UserCreate(email="not-an-email", password="p", tenant_slug="t")

    def test_user_read_fields(self):
        from scout.db.schemas import UserRead
        u = UserRead(
            id="u-001",
            email="alice@acme.com",
            tenant_id="t-001",
            role="admin",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        assert u.id == "u-001"
        assert u.role == "admin"

    def test_user_read_from_attributes(self):
        from scout.db.schemas import UserRead
        assert UserRead.model_config.get("from_attributes") is True

    def test_user_login_fields(self):
        from scout.db.schemas import UserLogin
        u = UserLogin(email="alice@acme.com", password="secret")
        assert u.email == "alice@acme.com"
        assert u.password == "secret"

    def test_user_login_validates_email(self):
        from scout.db.schemas import UserLogin
        with pytest.raises(Exception):
            UserLogin(email="bad-email", password="p")


class TestTokenSchema:

    def test_token_response_fields(self):
        from scout.db.schemas import TokenResponse
        t = TokenResponse(
            access_token="eyJ...",
            tenant_id="t-001",
            email="alice@acme.com",
        )
        assert t.access_token == "eyJ..."
        assert t.token_type == "bearer"  # default
        assert t.tenant_id == "t-001"

    def test_token_response_default_token_type(self):
        from scout.db.schemas import TokenResponse
        t = TokenResponse(access_token="tok", tenant_id="t", email="e@e.com")
        assert t.token_type == "bearer"


class TestApiKeySchemas:

    def test_api_key_create_requires_label(self):
        from scout.db.schemas import ApiKeyCreate
        k = ApiKeyCreate(label="CI/CD Pipeline")
        assert k.label == "CI/CD Pipeline"

    def test_api_key_create_missing_label_raises(self):
        from scout.db.schemas import ApiKeyCreate
        with pytest.raises(Exception):
            ApiKeyCreate()

    def test_api_key_read_fields(self):
        from scout.db.schemas import ApiKeyRead
        k = ApiKeyRead(
            id="k-001",
            key_prefix="sk-abc1",
            label="Dev Key",
            tenant_id="t-001",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_used_at=None,
        )
        assert k.id == "k-001"
        assert k.key_prefix == "sk-abc1"
        assert k.last_used_at is None

    def test_api_key_read_from_attributes(self):
        from scout.db.schemas import ApiKeyRead
        assert ApiKeyRead.model_config.get("from_attributes") is True

    def test_api_key_create_response_has_raw_key(self):
        from scout.db.schemas import ApiKeyCreateResponse
        k = ApiKeyCreateResponse(
            id="k-001",
            key_prefix="sk-abc1",
            label="Dev Key",
            tenant_id="t-001",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_used_at=None,
            raw_key="sk-supersecretfullkeyvalue",
        )
        assert k.raw_key == "sk-supersecretfullkeyvalue"
        # raw_key is on the create response but not on the base ApiKeyRead
        from scout.db.schemas import ApiKeyRead
        assert not hasattr(ApiKeyRead, "raw_key") or "raw_key" not in ApiKeyRead.model_fields
