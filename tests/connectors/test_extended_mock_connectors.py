"""
tests/connectors/test_extended_mock_connectors.py — Sprint 46: Extended mock connector coverage

Covers the 28 mock connectors that were previously untested.
salesforce, workday, and netsuite are already covered in test_mock_connectors.py —
this file covers the remainder via pytest parametrization.

Every mock connector must satisfy the same ConnectorBase contract:
  - Class attributes: CONNECTOR_ID (str), DISPLAY_NAME (str), CATEGORY, CALLS_PER_SECOND > 0
  - authenticate() → True
  - discover_schema() → non-empty list[EntitySchema]
  - extract_full(entity_type) → yields RawRecord objects with correct fields
  - health_check() → ConnectorHealth(is_healthy=True)
  - extract_full(unknown_entity_type) → raises ValueError

All tests run with NO external dependencies.
"""

import importlib
from datetime import datetime

import pytest

from scout.connectors.base import ConnectorBase
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ExtractionCursor,
    RawRecord,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONNECTOR REGISTRY
# Each entry: (module_path, class_name, connector_id)
# ─────────────────────────────────────────────────────────────────────────────

_CONNECTORS = [
    ("scout.connectors.mock.acumatica",      "AcumaticaMockConnector",      "acumatica"),
    ("scout.connectors.mock.adp",            "ADPMockConnector",             "adp"),
    ("scout.connectors.mock.azure_ad",       "AzureADMockConnector",         "azure_ad"),
    ("scout.connectors.mock.bamboohr",       "BambooHRMockConnector",        "bamboohr"),
    ("scout.connectors.mock.billcom",        "BillcomMockConnector",         "billcom"),
    ("scout.connectors.mock.brex",           "BrexMockConnector",            "brex"),
    ("scout.connectors.mock.concur",         "ConcurMockConnector",          "concur"),
    ("scout.connectors.mock.coupa",          "CoupaMockConnector",           "coupa"),
    ("scout.connectors.mock.dynamics_crm",   "DynamicsCRMMockConnector",     "dynamics_crm"),
    ("scout.connectors.mock.dynamics_finance", "DynamicsFinanceMockConnector", "dynamics_finance"),
    ("scout.connectors.mock.epicor",         "EpicorMockConnector",          "epicor"),
    ("scout.connectors.mock.freshservice",   "FreshserviceMockConnector",    "freshservice"),
    ("scout.connectors.mock.google_workspace", "GoogleWorkspaceMockConnector", "google_workspace"),
    ("scout.connectors.mock.gusto",          "GustoMockConnector",           "gusto"),
    ("scout.connectors.mock.hubspot",        "HubSpotMockConnector",         "hubspot"),
    ("scout.connectors.mock.jira",           "JiraMockConnector",            "jira"),
    ("scout.connectors.mock.jumpcloud",      "JumpCloudMockConnector",       "jumpcloud"),
    ("scout.connectors.mock.okta",           "OktaMockConnector",            "okta"),
    ("scout.connectors.mock.pipedrive",      "PipedriveMockConnector",       "pipedrive"),
    ("scout.connectors.mock.quickbooks",     "QuickBooksMockConnector",      "quickbooks"),
    ("scout.connectors.mock.ramp",           "RampMockConnector",            "ramp"),
    ("scout.connectors.mock.rippling",       "RipplingMockConnector",        "rippling"),
    ("scout.connectors.mock.sage_intacct",   "SageIntacctMockConnector",     "sage_intacct"),
    ("scout.connectors.mock.sap",            "SAPMockConnector",             "sap"),
    ("scout.connectors.mock.servicenow",     "ServiceNowMockConnector",      "servicenow"),
    ("scout.connectors.mock.ukg",            "UKGMockConnector",             "ukg"),
    ("scout.connectors.mock.zendesk",        "ZendeskMockConnector",         "zendesk"),
    ("scout.connectors.mock.zoho",           "ZohoMockConnector",            "zoho"),
]


def _make_creds(connector_id: str) -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id=connector_id,
        tenant_id="test-tenant",
        auth_data={"token": "test-token-xyz"},
    )


def _load_connector(module_path: str, class_name: str, connector_id: str) -> ConnectorBase:
    """Dynamically import and instantiate a connector."""
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls(_make_creds(connector_id))


# Build parametrize IDs from connector_id for readable test names
_PARAM_IDS = [entry[2] for entry in _CONNECTORS]
_PARAM_VALS = [(m, c, cid) for m, c, cid in _CONNECTORS]


# ─────────────────────────────────────────────────────────────────────────────
# PARAMETRIZED INTERFACE TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("module_path,class_name,connector_id", _PARAM_VALS, ids=_PARAM_IDS)
class TestMockConnectorInterface:
    """Every mock connector must pass these 8 tests."""

    def _connector(self, module_path, class_name, connector_id):
        return _load_connector(module_path, class_name, connector_id)

    def test_implements_connector_base(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        assert isinstance(c, ConnectorBase)

    def test_connector_id_matches_expected(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        assert c.CONNECTOR_ID == connector_id

    def test_display_name_is_nonempty_string(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        assert isinstance(c.DISPLAY_NAME, str)
        assert len(c.DISPLAY_NAME) > 0

    def test_category_is_connector_category(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        assert isinstance(c.CATEGORY, ConnectorCategory)

    def test_calls_per_second_is_positive(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        assert isinstance(c.CALLS_PER_SECOND, (int, float))
        assert c.CALLS_PER_SECOND > 0

    def test_authenticate_returns_true(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        assert c.authenticate() is True

    def test_discover_schema_returns_nonempty_list(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        schema = c.discover_schema()
        assert isinstance(schema, list)
        assert len(schema) >= 1

    def test_health_check_is_healthy(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        health = c.health_check()
        assert health.is_healthy is True
        assert health.connector_id == connector_id
        assert health.latency_ms >= 0


# ─────────────────────────────────────────────────────────────────────────────
# PARAMETRIZED EXTRACTION TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("module_path,class_name,connector_id", _PARAM_VALS, ids=_PARAM_IDS)
class TestMockConnectorExtraction:
    """Full and incremental extraction must yield valid RawRecords."""

    def _connector(self, module_path, class_name, connector_id):
        return _load_connector(module_path, class_name, connector_id)

    def test_extract_full_yields_at_least_one_record(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        first_entity_type = c.discover_schema()[0].entity_type
        records = list(c.extract_full(first_entity_type))
        assert len(records) >= 1

    def test_extract_full_records_are_raw_records(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        first_entity_type = c.discover_schema()[0].entity_type
        for record in c.extract_full(first_entity_type):
            assert isinstance(record, RawRecord)
            break  # only need to check first

    def test_extract_full_records_have_correct_connector_id(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        first_entity_type = c.discover_schema()[0].entity_type
        for record in c.extract_full(first_entity_type):
            assert record.connector_id == connector_id
            break

    def test_extract_full_records_have_correct_tenant_id(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        first_entity_type = c.discover_schema()[0].entity_type
        for record in c.extract_full(first_entity_type):
            assert record.tenant_id == "test-tenant"
            break

    def test_extract_full_records_have_source_id(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        first_entity_type = c.discover_schema()[0].entity_type
        for record in c.extract_full(first_entity_type):
            assert record.source_id is not None
            assert str(record.source_id) != ""
            break

    def test_extract_full_records_have_nonempty_payload(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        first_entity_type = c.discover_schema()[0].entity_type
        for record in c.extract_full(first_entity_type):
            assert isinstance(record.payload, dict)
            assert len(record.payload) > 0
            break

    def test_extract_full_unknown_entity_type_raises_value_error(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        with pytest.raises((ValueError, KeyError)):
            list(c.extract_full("__nonexistent_entity_type__"))

    def test_extract_incremental_returns_iterator_and_cursor(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        first_entity_type = c.discover_schema()[0].entity_type
        cursor = ExtractionCursor(
            connector_id=connector_id,
            entity_type=first_entity_type,
            last_extracted_at=datetime.utcnow(),
            checkpoint={"from_date": "2024-01-01"},
        )
        records_gen, new_cursor = c.extract_incremental(first_entity_type, cursor)
        # Consume the generator — should not error
        records = list(records_gen)
        assert isinstance(records, list)
        # All returned records (if any) must be RawRecord
        for r in records:
            assert isinstance(r, RawRecord)
        # Cursor must be updated
        assert new_cursor is not None
        assert new_cursor.connector_id == connector_id


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA COMPLETENESS — each schema entry must be well-formed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("module_path,class_name,connector_id", _PARAM_VALS, ids=_PARAM_IDS)
class TestMockConnectorSchema:
    """EntitySchema objects returned by discover_schema() must be valid."""

    def _connector(self, module_path, class_name, connector_id):
        return _load_connector(module_path, class_name, connector_id)

    def test_all_schema_entries_have_entity_type(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        for schema in c.discover_schema():
            assert isinstance(schema.entity_type, str)
            assert len(schema.entity_type) > 0

    def test_all_schema_entries_have_display_name(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        for schema in c.discover_schema():
            assert isinstance(schema.display_name, str)
            assert len(schema.display_name) > 0

    def test_all_schema_entries_have_nonnegative_record_count(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        for schema in c.discover_schema():
            assert schema.estimated_record_count >= 0

    def test_schema_entity_types_match_extract_full(self, module_path, class_name, connector_id):
        """Every entity type in the schema must be extractable without error."""
        c = self._connector(module_path, class_name, connector_id)
        for schema in c.discover_schema():
            records = list(c.extract_full(schema.entity_type))
            assert isinstance(records, list)

    def test_no_duplicate_entity_types_in_schema(self, module_path, class_name, connector_id):
        c = self._connector(module_path, class_name, connector_id)
        entity_types = [s.entity_type for s in c.discover_schema()]
        assert len(entity_types) == len(set(entity_types))

    def test_connector_id_preserved_across_all_entity_types(self, module_path, class_name, connector_id):
        """extract_full must stamp connector_id on every record, for every entity type."""
        c = self._connector(module_path, class_name, connector_id)
        for schema in c.discover_schema():
            for record in c.extract_full(schema.entity_type):
                assert record.connector_id == connector_id
