"""
tests/graph/test_schema.py — Unit tests for graph schema constants (Sprint 41)

The graph schema module defines Neo4j CONSTRAINTS and INDEXES as string
constants. These tests validate the structure, completeness, and correctness
of those constants WITHOUT requiring a live Neo4j connection.

Coverage:
  - CONSTRAINTS list: presence, idempotency (IF NOT EXISTS), node labels covered
  - INDEXES list: presence, idempotency, properties covered
  - DROPPED_CONSTRAINTS: valid DROP syntax with IF EXISTS
  - All four entity types (Person, Vendor, Account, Opportunity) have canonical_id constraints
  - Key query properties are indexed (department, is_active, employment_type, stage, etc.)
"""

import pytest

from scout.graph.schema import CONSTRAINTS, DROPPED_CONSTRAINTS, INDEXES


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRAINTS
# ─────────────────────────────────────────────────────────────────────────────

class TestConstraints:

    def test_constraints_list_is_not_empty(self):
        assert len(CONSTRAINTS) > 0

    def test_all_constraints_are_strings(self):
        for c in CONSTRAINTS:
            assert isinstance(c, str), f"Expected string, got {type(c)}: {c!r}"

    def test_all_constraints_use_if_not_exists(self):
        """Idempotency: every CREATE CONSTRAINT must include IF NOT EXISTS."""
        for c in CONSTRAINTS:
            if c.strip().upper().startswith("CREATE CONSTRAINT"):
                assert "IF NOT EXISTS" in c, (
                    f"Constraint missing IF NOT EXISTS (not idempotent): {c!r}"
                )

    def test_person_canonical_id_constraint_exists(self):
        found = any("Person" in c and "canonical_id" in c for c in CONSTRAINTS)
        assert found, "No canonical_id uniqueness constraint found for :Person"

    def test_vendor_canonical_id_constraint_exists(self):
        found = any("Vendor" in c and "canonical_id" in c for c in CONSTRAINTS)
        assert found, "No canonical_id uniqueness constraint found for :Vendor"

    def test_account_canonical_id_constraint_exists(self):
        found = any("Account" in c and "canonical_id" in c for c in CONSTRAINTS)
        assert found, "No canonical_id uniqueness constraint found for :Account"

    def test_opportunity_canonical_id_constraint_exists(self):
        found = any("Opportunity" in c and "canonical_id" in c for c in CONSTRAINTS)
        assert found, "No canonical_id uniqueness constraint found for :Opportunity"

    def test_person_tenant_email_composite_constraint_exists(self):
        """Multi-tenant safety: (tenant_id, email) uniqueness on Person."""
        found = any(
            "Person" in c and "tenant_id" in c and "email" in c
            for c in CONSTRAINTS
        )
        assert found, "No composite (tenant_id, email) constraint found for :Person"

    def test_all_constraints_start_with_create_or_drop(self):
        for c in CONSTRAINTS:
            stripped = c.strip().upper()
            assert stripped.startswith("CREATE") or stripped.startswith("DROP"), (
                f"Unexpected constraint statement: {c!r}"
            )

    def test_constraint_count_at_least_four(self):
        """At minimum: Person canonical_id, Vendor, Account, Opportunity."""
        assert len(CONSTRAINTS) >= 4

    def test_no_duplicate_constraint_statements(self):
        normalized = [c.strip().lower() for c in CONSTRAINTS]
        assert len(normalized) == len(set(normalized)), "Duplicate constraint statements found"


# ─────────────────────────────────────────────────────────────────────────────
# INDEXES
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexes:

    def test_indexes_list_is_not_empty(self):
        assert len(INDEXES) > 0

    def test_all_indexes_are_strings(self):
        for idx in INDEXES:
            assert isinstance(idx, str), f"Expected string, got {type(idx)}: {idx!r}"

    def test_all_indexes_use_if_not_exists(self):
        """Idempotency: every CREATE INDEX must include IF NOT EXISTS."""
        for idx in INDEXES:
            if idx.strip().upper().startswith("CREATE INDEX"):
                assert "IF NOT EXISTS" in idx, (
                    f"Index missing IF NOT EXISTS (not idempotent): {idx!r}"
                )

    def test_person_department_index_exists(self):
        found = any("Person" in idx and "department" in idx for idx in INDEXES)
        assert found, "No index found for Person.department"

    def test_person_is_active_index_exists(self):
        found = any("Person" in idx and "is_active" in idx for idx in INDEXES)
        assert found, "No index found for Person.is_active"

    def test_person_employment_type_index_exists(self):
        found = any("Person" in idx and "employment_type" in idx for idx in INDEXES)
        assert found, "No index found for Person.employment_type"

    def test_person_tenant_index_exists(self):
        found = any("Person" in idx and "tenant_id" in idx for idx in INDEXES)
        assert found, "No tenant_id index found for Person (needed for multi-tenant isolation)"

    def test_vendor_category_index_exists(self):
        found = any("Vendor" in idx and "category" in idx for idx in INDEXES)
        assert found, "No index found for Vendor.category"

    def test_vendor_annual_spend_index_exists(self):
        found = any("Vendor" in idx and "annual_spend" in idx for idx in INDEXES)
        assert found, "No index found for Vendor.annual_spend"

    def test_vendor_contract_renewal_index_exists(self):
        found = any("Vendor" in idx and "contract_renewal" in idx for idx in INDEXES)
        assert found, "No index found for Vendor.contract_renewal (needed for renewal worker)"

    def test_opportunity_stage_index_exists(self):
        found = any("Opportunity" in idx and "stage" in idx for idx in INDEXES)
        assert found, "No index found for Opportunity.stage"

    def test_opportunity_is_closed_index_exists(self):
        found = any("Opportunity" in idx and "is_closed" in idx for idx in INDEXES)
        assert found, "No index found for Opportunity.is_closed"

    def test_opportunity_close_date_index_exists(self):
        found = any("Opportunity" in idx and "close_date" in idx for idx in INDEXES)
        assert found, "No index found for Opportunity.close_date"

    def test_account_covered(self):
        found = any("Account" in idx for idx in INDEXES)
        assert found, "No indexes found for Account nodes"

    def test_index_count_at_least_ten(self):
        """Sanity: at least 10 indexes across four entity types."""
        assert len(INDEXES) >= 10

    def test_no_duplicate_index_statements(self):
        normalized = [idx.strip().lower() for idx in INDEXES]
        assert len(normalized) == len(set(normalized)), "Duplicate index statements found"

    def test_all_indexes_start_with_create_index(self):
        for idx in INDEXES:
            stripped = idx.strip().upper()
            assert stripped.startswith("CREATE INDEX"), (
                f"Unexpected statement in INDEXES list: {idx!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# DROPPED CONSTRAINTS (migrations)
# ─────────────────────────────────────────────────────────────────────────────

class TestDroppedConstraints:

    def test_dropped_constraints_is_a_list(self):
        assert isinstance(DROPPED_CONSTRAINTS, list)

    def test_all_dropped_constraints_are_strings(self):
        for c in DROPPED_CONSTRAINTS:
            assert isinstance(c, str)

    def test_all_dropped_use_drop_constraint(self):
        for c in DROPPED_CONSTRAINTS:
            assert c.strip().upper().startswith("DROP CONSTRAINT"), (
                f"DROPPED_CONSTRAINTS should only contain DROP CONSTRAINT statements: {c!r}"
            )

    def test_all_dropped_use_if_exists(self):
        """Idempotency: DROP statements must use IF EXISTS."""
        for c in DROPPED_CONSTRAINTS:
            assert "IF EXISTS" in c.upper(), (
                f"DROP CONSTRAINT missing IF EXISTS (will error if already dropped): {c!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# CONSISTENCY: constraints don't re-define what indexes already cover
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaConsistency:

    def test_indexes_and_constraints_together_cover_all_four_entity_types(self):
        all_statements = CONSTRAINTS + INDEXES
        entity_labels = {"Person", "Vendor", "Account", "Opportunity"}
        covered = {label for label in entity_labels if any(label in s for s in all_statements)}
        assert covered == entity_labels, (
            f"Missing schema coverage for: {entity_labels - covered}"
        )

    def test_total_schema_statement_count_reasonable(self):
        """Total must be >= 15 (4 constraints + 11+ indexes) and < 100 (no bloat)."""
        total = len(CONSTRAINTS) + len(INDEXES)
        assert 15 <= total < 100, f"Unexpected schema statement count: {total}"
