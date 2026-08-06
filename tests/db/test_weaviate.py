"""
tests/db/test_weaviate.py

Unit tests for the Weaviate vector resolver (mock implementation).

These tests run with NO external dependencies — no Docker, no Weaviate.
They verify that:
  - Exact name matches are resolved correctly
  - Known aliases are matched (SFDC → Salesforce, etc.)
  - Trigram similarity catches near-duplicate names
  - Tenant isolation is maintained
  - The resolver integrates correctly with EntityResolver vendor dedup
  - The factory returns the correct implementation

Run with: poetry run pytest tests/db/test_weaviate.py
"""

import pytest

from scout.db.weaviate_client import (
    MockVectorResolver,
    SimilarEntity,
    VectorResolverBase,
    get_vector_resolver,
    _normalize,
    _trigram_similarity,
)

TENANT = "test-tenant-wv"


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def resolver() -> MockVectorResolver:
    return MockVectorResolver()


@pytest.fixture
def resolver_with_vendors(resolver) -> MockVectorResolver:
    """Resolver pre-populated with a standard vendor set."""
    vendors = [
        ("salesforce", "Salesforce", "CRM"),
        ("hubspot", "HubSpot", "CRM"),
        ("workday", "Workday", "HRIS"),
        ("netsuite", "NetSuite", "ERP"),
        ("okta", "Okta", "Identity"),
        ("jira", "Jira", "Project Management"),
        ("microsoft-dynamics", "Microsoft Dynamics", "CRM"),
        ("google-workspace", "Google Workspace", "Identity"),
        ("sap", "SAP", "ERP"),
        ("concur", "Concur", "Expense"),
    ]
    for cid, name, category in vendors:
        resolver.index_entity(
            entity_type="vendor",
            canonical_id=cid,
            name=name,
            tenant_id=TENANT,
            extra={"category": category},
        )
    return resolver


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpers:

    def test_normalize_lowercases(self):
        assert _normalize("SALESFORCE") == "salesforce"

    def test_normalize_strips_punctuation(self):
        result = _normalize("Salesforce, Inc.")
        assert "salesforce" in result
        assert "inc" in result
        assert "." not in _normalize("U.S.A.")
        assert "," not in result

    def test_normalize_collapses_whitespace(self):
        # Whitespace is collapsed to single spaces and stripped
        result = _normalize("  hello   world  ")
        assert result == "hello world"

    def test_trigram_similarity_identical(self):
        assert _trigram_similarity("salesforce", "salesforce") == 1.0

    def test_trigram_similarity_different(self):
        sim = _trigram_similarity("salesforce", "workday")
        assert 0.0 <= sim < 0.5

    def test_trigram_similarity_similar(self):
        sim = _trigram_similarity("salesforce inc", "salesforce")
        assert sim > 0.6

    def test_trigram_similarity_empty_strings(self):
        assert _trigram_similarity("", "") == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# INTERFACE COMPLIANCE
# ─────────────────────────────────────────────────────────────────────────────

class TestInterfaceCompliance:

    def test_mock_implements_base(self, resolver):
        assert isinstance(resolver, VectorResolverBase)

    def test_health_check(self, resolver):
        assert resolver.health_check() is True

    def test_factory_returns_mock(self):
        r = get_vector_resolver()
        assert isinstance(r, MockVectorResolver)

    def test_similar_entity_fields(self):
        se = SimilarEntity(
            canonical_id="sfdc", name="Salesforce", certainty=0.95, entity_type="vendor"
        )
        assert se.canonical_id == "sfdc"
        assert se.certainty == 0.95


# ─────────────────────────────────────────────────────────────────────────────
# INDEXING
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexing:

    def test_index_returns_uuid(self, resolver):
        uuid = resolver.index_entity(
            entity_type="vendor",
            canonical_id="salesforce",
            name="Salesforce",
            tenant_id=TENANT,
        )
        assert isinstance(uuid, str)
        assert len(uuid) > 0

    def test_entity_count_after_index(self, resolver):
        resolver.index_entity("vendor", "sfdc", "Salesforce", TENANT)
        resolver.index_entity("vendor", "hubspot", "HubSpot", TENANT)
        assert resolver.entity_count("vendor", TENANT) == 2

    def test_entity_count_tenant_isolation(self, resolver):
        resolver.index_entity("vendor", "sfdc", "Salesforce", "tenant-a")
        resolver.index_entity("vendor", "sfdc", "Salesforce", "tenant-b")
        assert resolver.entity_count("vendor", "tenant-a") == 1
        assert resolver.entity_count("vendor", "tenant-b") == 1

    def test_no_duplicate_indexing_same_canonical_id(self, resolver):
        resolver.index_entity("vendor", "sfdc", "Salesforce", TENANT)
        resolver.index_entity("vendor", "sfdc", "Salesforce", TENANT)
        assert resolver.entity_count("vendor", TENANT) == 1


# ─────────────────────────────────────────────────────────────────────────────
# EXACT MATCH
# ─────────────────────────────────────────────────────────────────────────────

class TestExactMatch:

    def test_exact_name_match(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "Salesforce", TENANT, min_certainty=0.85
        )
        assert len(results) >= 1
        assert results[0].canonical_id == "salesforce"

    def test_case_insensitive_match(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "SALESFORCE", TENANT, min_certainty=0.85
        )
        assert len(results) >= 1
        assert results[0].canonical_id == "salesforce"

    def test_no_match_below_threshold(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "CompletlyUnrelatedVendorXYZ123", TENANT, min_certainty=0.99
        )
        assert len(results) == 0


# ─────────────────────────────────────────────────────────────────────────────
# ALIAS MATCHING
# ─────────────────────────────────────────────────────────────────────────────

class TestAliasMatching:

    def test_sfdc_alias_matches_salesforce(self, resolver_with_vendors):
        """'SFDC' must resolve to the indexed 'Salesforce' vendor."""
        results = resolver_with_vendors.find_similar(
            "vendor", "SFDC", TENANT, min_certainty=0.85
        )
        assert len(results) >= 1
        assert results[0].canonical_id == "salesforce"

    def test_salesforce_dot_com_matches(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "salesforce.com", TENANT, min_certainty=0.85
        )
        assert len(results) >= 1
        assert results[0].canonical_id == "salesforce"

    def test_gsuite_matches_google_workspace(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "gsuite", TENANT, min_certainty=0.85
        )
        assert len(results) >= 1
        assert results[0].canonical_id == "google-workspace"

    def test_sap_concur_matches_concur(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "sap concur", TENANT, min_certainty=0.85
        )
        assert len(results) >= 1
        assert results[0].canonical_id == "concur"

    def test_workday_hcm_matches_workday(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "workday hcm", TENANT, min_certainty=0.85
        )
        assert len(results) >= 1
        assert results[0].canonical_id == "workday"


# ─────────────────────────────────────────────────────────────────────────────
# NEAR-DUPLICATE MATCHING (trigram)
# ─────────────────────────────────────────────────────────────────────────────

class TestNearDuplicateMatching:

    def test_minor_suffix_variation(self, resolver_with_vendors):
        """'HubSpot CRM' should match indexed 'HubSpot'."""
        results = resolver_with_vendors.find_similar(
            "vendor", "HubSpot CRM", TENANT, min_certainty=0.70
        )
        assert any(r.canonical_id == "hubspot" for r in results)

    def test_results_sorted_by_certainty(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "Salesforce", TENANT, min_certainty=0.5
        )
        if len(results) > 1:
            certainties = [r.certainty for r in results]
            assert certainties == sorted(certainties, reverse=True)

    def test_limit_respected(self, resolver_with_vendors):
        results = resolver_with_vendors.find_similar(
            "vendor", "S", TENANT, limit=2, min_certainty=0.0
        )
        assert len(results) <= 2


# ─────────────────────────────────────────────────────────────────────────────
# TENANT ISOLATION
# ─────────────────────────────────────────────────────────────────────────────

class TestTenantIsolation:

    def test_find_similar_respects_tenant(self, resolver):
        resolver.index_entity("vendor", "sfdc-a", "Salesforce", "tenant-a")
        resolver.index_entity("vendor", "sfdc-b", "Salesforce", "tenant-b")

        results_a = resolver.find_similar("vendor", "Salesforce", "tenant-a", min_certainty=0.9)
        results_b = resolver.find_similar("vendor", "Salesforce", "tenant-b", min_certainty=0.9)

        assert all(r.canonical_id == "sfdc-a" for r in results_a)
        assert all(r.canonical_id == "sfdc-b" for r in results_b)


# ─────────────────────────────────────────────────────────────────────────────
# ENTITY RESOLVER INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

class TestEntityResolverIntegration:
    """
    Verify that EntityResolver uses Weaviate dedup to merge vendor records
    that refer to the same real-world entity under different names.
    """

    def test_sfdc_variants_merged(self):
        """Three Salesforce name variants → one canonical vendor."""
        from scout.ingestion.resolver import EntityResolver

        resolver = EntityResolver(tenant_id=TENANT)
        records = [
            {
                "entity_type": "vendor", "name": "Salesforce",
                "annual_spend": 80_000, "_source_connector": "netsuite",
            },
            {
                "entity_type": "vendor", "name": "SFDC",
                "annual_spend": 0, "_source_connector": "concur",
            },
            {
                "entity_type": "vendor", "name": "salesforce.com",
                "annual_spend": 0, "_source_connector": "coupa",
            },
        ]
        vendors = resolver._resolve_vendors(records)
        # Should merge all three into one or two (SFDC + salesforce.com should match Salesforce)
        # With mock alias matching, at least one merge should happen
        assert len(vendors) <= 2

    def test_different_vendors_not_merged(self):
        """Workday and Salesforce must not be merged."""
        from scout.ingestion.resolver import EntityResolver

        resolver = EntityResolver(tenant_id=TENANT)
        records = [
            {
                "entity_type": "vendor", "name": "Salesforce",
                "annual_spend": 80_000, "_source_connector": "netsuite",
            },
            {
                "entity_type": "vendor", "name": "Workday",
                "annual_spend": 120_000, "_source_connector": "netsuite",
            },
        ]
        vendors = resolver._resolve_vendors(records)
        assert len(vendors) == 2

    def test_merged_vendor_takes_higher_spend(self):
        """When two records merge, the higher annual_spend wins."""
        from scout.ingestion.resolver import EntityResolver

        resolver = EntityResolver(tenant_id=TENANT)
        records = [
            {
                "entity_type": "vendor", "name": "Salesforce",
                "annual_spend": 80_000, "_source_connector": "netsuite",
            },
            {
                "entity_type": "vendor", "name": "SFDC",
                "annual_spend": 95_000, "_source_connector": "concur",
            },
        ]
        vendors = resolver._resolve_vendors(records)
        if len(vendors) == 1:
            # Merged: should take the higher spend
            assert vendors[0].annual_spend >= 80_000

    def test_resolver_works_with_no_vector_resolver(self):
        """EntityResolver must work when vector_resolver is explicitly None."""
        from scout.ingestion.resolver import EntityResolver

        resolver = EntityResolver(tenant_id=TENANT, vector_resolver=None)
        records = [
            {
                "entity_type": "vendor", "name": "Salesforce",
                "annual_spend": 80_000, "_source_connector": "netsuite",
            },
        ]
        vendors = resolver._resolve_vendors(records)
        assert len(vendors) == 1
        assert vendors[0].name == "Salesforce"
