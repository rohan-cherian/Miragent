"""Tests for entity resolution — merging cross-system duplicates."""

import pytest
from scout.ingestion.resolver import EntityResolver


def make_person_record(connector: str, email: str, **kwargs) -> dict:
    """Helper to create a normalized person record."""
    return {
        "entity_type": "person",
        "_source_connector": connector,
        "_source_id": f"{connector}-123",
        "_entity_type": "person",
        "_tenant_id": "test-tenant",
        "email": email,
        "full_name": kwargs.get("full_name", "Test User"),
        "job_title": kwargs.get("job_title"),
        "department": kwargs.get("department"),
        "is_active": kwargs.get("is_active", True),
        "employment_type": kwargs.get("employment_type"),
        "workday_id": kwargs.get("workday_id"),
        "salesforce_id": kwargs.get("salesforce_id"),
        "employee_id": kwargs.get("employee_id"),
        "manager_workday_id": kwargs.get("manager_workday_id"),
        "location": kwargs.get("location"),
        "cost_center": kwargs.get("cost_center"),
        "start_date": kwargs.get("start_date"),
        "last_login_sfdc": kwargs.get("last_login_sfdc"),
    }


class TestPersonResolution:

    def setup_method(self):
        self.resolver = EntityResolver(tenant_id="test-tenant")

    def test_same_email_merges_to_one_person(self):
        """The core test: two records with the same email → one canonical person."""
        records = [
            make_person_record("workday", "s.chen@acmecorp.com",
                               full_name="Sarah Chen", job_title="VP of Sales",
                               workday_id="WD-0001", department="Sales"),
            make_person_record("salesforce", "s.chen@acmecorp.com",
                               full_name="Sarah Chen", job_title="VP of Sales",
                               salesforce_id="005abc"),
        ]
        persons, _, _, _ = self.resolver.resolve(records)
        assert len(persons) == 1
        person = persons[0]
        assert person.email == "s.chen@acmecorp.com"
        assert person.full_name == "Sarah Chen"

    def test_merged_person_has_both_source_ids(self):
        """After merging Workday + Salesforce, the person retains both system IDs."""
        records = [
            make_person_record("workday", "s.chen@acmecorp.com",
                               workday_id="WD-0001"),
            make_person_record("salesforce", "s.chen@acmecorp.com",
                               salesforce_id="005abc"),
        ]
        persons, _, _, _ = self.resolver.resolve(records)
        person = persons[0]
        assert person.workday_id == "WD-0001"
        assert person.salesforce_id == "005abc"
        assert "workday" in person.source_systems
        assert "salesforce" in person.source_systems

    def test_workday_wins_over_salesforce_for_department(self):
        """Source-of-truth hierarchy: Workday beats Salesforce for people fields."""
        records = [
            make_person_record("salesforce", "m.johnson@acmecorp.com",
                               department="Sales Ops"),     # wrong in SFDC
            make_person_record("workday", "m.johnson@acmecorp.com",
                               department="Sales"),         # correct in Workday
        ]
        persons, _, _, _ = self.resolver.resolve(records)
        person = persons[0]
        assert person.department == "Sales"  # Workday wins

    def test_different_emails_create_different_persons(self):
        """Different emails → different people → no merging."""
        records = [
            make_person_record("workday", "sarah@acmecorp.com", full_name="Sarah"),
            make_person_record("workday", "marcus@acmecorp.com", full_name="Marcus"),
        ]
        persons, _, _, _ = self.resolver.resolve(records)
        assert len(persons) == 2

    def test_canonical_id_is_stable(self):
        """Same email → same canonical_id every time. Critical for idempotency."""
        records = [make_person_record("workday", "s.chen@acmecorp.com")]
        persons1, _, _, _ = self.resolver.resolve(records)
        persons2, _, _, _ = self.resolver.resolve(records)
        assert persons1[0].canonical_id == persons2[0].canonical_id

    def test_multi_source_has_higher_confidence(self):
        """A person matched across two systems gets confidence 1.0."""
        records = [
            make_person_record("workday", "s.chen@acmecorp.com"),
            make_person_record("salesforce", "s.chen@acmecorp.com"),
        ]
        persons, _, _, _ = self.resolver.resolve(records)
        assert persons[0].confidence_score == 1.0

    def test_employment_type_from_workday(self):
        """Employment type (Regular vs Contractor) must come from Workday."""
        records = [
            make_person_record("workday", "c.mendez@acmecorp.com",
                               employment_type="Contractor"),
        ]
        persons, _, _, _ = self.resolver.resolve(records)
        assert persons[0].employment_type == "Contractor"


class TestManagerResolution:

    def test_manager_relationships_resolved(self):
        """Workers with managerId should get manager_canonical_id populated."""
        resolver = EntityResolver(tenant_id="test-tenant")
        records = [
            make_person_record("workday", "sarah@co.com",
                               workday_id="WD-0001", manager_workday_id=None),
            make_person_record("workday", "marcus@co.com",
                               workday_id="WD-0010", manager_workday_id="WD-0001"),
        ]
        persons, _, _, _ = resolver.resolve(records)

        # Build manager map as the pipeline would
        manager_map = {"WD-0001": None, "WD-0010": "WD-0001"}
        resolver.resolve_person_managers(persons, manager_map)

        marcus = next(p for p in persons if "marcus" in p.email)
        sarah = next(p for p in persons if "sarah" in p.email)

        assert marcus.manager_canonical_id == sarah.canonical_id


class TestVendorResolution:

    def test_each_vendor_becomes_canonical(self):
        resolver = EntityResolver(tenant_id="test-tenant")
        records = [
            {"entity_type": "vendor", "_source_connector": "netsuite",
             "_source_id": "V-001", "_tenant_id": "test-tenant",
             "name": "Salesforce Inc", "normalized_name": "salesforce-inc",
             "annual_spend": 284000.0, "category": "Software",
             "contract_renewal": "2024-09-30", "is_active": True},
        ]
        _, vendors, _, _ = resolver.resolve(records)
        assert len(vendors) == 1
        assert vendors[0].name == "Salesforce Inc"
        assert vendors[0].annual_spend == 284000.0
