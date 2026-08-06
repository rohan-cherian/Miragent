"""
scout/connectors/registry.py — The connector registry.

This is the single place where connector implementations are mapped
to their IDs. The orchestrator asks the registry for a connector;
the registry decides whether to return the real or mock version
based on the environment configuration.

This is Dependency Injection in practice:
  - Development (USE_MOCK_CONNECTORS=true):  returns mock connectors
  - Production (USE_MOCK_CONNECTORS=false):  returns real connectors
  - The orchestrator code never changes between environments
"""

from scout.config import settings
from scout.connectors.base import ConnectorBase
from scout.connectors.models import ConnectorCredentials

# ── Import mock connectors (always available) ──────────────────────────────────
from scout.connectors.mock.salesforce import SalesforceMockConnector
from scout.connectors.mock.workday import WorkdayMockConnector
from scout.connectors.mock.netsuite import NetsuiteMockConnector

# HCM
from scout.connectors.mock.bamboohr import BambooHRMockConnector
from scout.connectors.mock.adp import ADPMockConnector
from scout.connectors.mock.rippling import RipplingMockConnector
from scout.connectors.mock.ukg import UKGMockConnector
from scout.connectors.mock.gusto import GustoMockConnector

# CRM
from scout.connectors.mock.hubspot import HubSpotMockConnector
from scout.connectors.mock.dynamics_crm import DynamicsCRMMockConnector
from scout.connectors.mock.pipedrive import PipedriveMockConnector
from scout.connectors.mock.zoho import ZohoMockConnector

# ERP
from scout.connectors.mock.quickbooks import QuickBooksMockConnector
from scout.connectors.mock.sap import SAPMockConnector
from scout.connectors.mock.dynamics_finance import DynamicsFinanceMockConnector
from scout.connectors.mock.sage_intacct import SageIntacctMockConnector
from scout.connectors.mock.acumatica import AcumaticaMockConnector
from scout.connectors.mock.epicor import EpicorMockConnector

# Identity
from scout.connectors.mock.okta import OktaMockConnector
from scout.connectors.mock.azure_ad import AzureADMockConnector
from scout.connectors.mock.google_workspace import GoogleWorkspaceMockConnector
from scout.connectors.mock.jumpcloud import JumpCloudMockConnector

# ITSM / SCM
from scout.connectors.mock.servicenow import ServiceNowMockConnector
from scout.connectors.mock.jira import JiraMockConnector
from scout.connectors.mock.zendesk import ZendeskMockConnector
from scout.connectors.mock.freshservice import FreshserviceMockConnector
from scout.connectors.mock.github import GitHubMockConnector

# Finance / Spend
from scout.connectors.mock.coupa import CoupaMockConnector
from scout.connectors.mock.ramp import RampMockConnector
from scout.connectors.mock.brex import BrexMockConnector
from scout.connectors.mock.concur import ConcurMockConnector
from scout.connectors.mock.billcom import BillcomMockConnector

# ── Import real connectors ────────────────────────────────────────────────────
# Production connectors. Activated when USE_MOCK_CONNECTORS=false.
# Sprint 12: Salesforce, HubSpot, Workday, Enrichment
# Sprint 29: BambooHR, Rippling, Sage Intacct, NetSuite
# Sprint 30: ADP, UKG
# Sprint 31: Okta, Azure AD
# Sprint 32: SAP, Oracle ERP, Dynamics 365
# Sprint 33: Dynamics CRM, Zoho CRM
# Sprint 34: ServiceNow, Jira
# Sprint 35: Zendesk, Freshservice
# Sprint 36: Ramp, Brex, Coupa
# Sprint 37: Concur, Bill.com, Google Workspace, JumpCloud, QuickBooks, Gusto, Pipedrive
# Sprint 38: Acumatica, Epicor, Dynamics 365 Finance
from scout.connectors.salesforce import SalesforceConnector
from scout.connectors.hubspot import HubSpotConnector
from scout.connectors.workday import WorkdayConnector
from scout.connectors.enrichment import ClearbitConnector, ZoomInfoConnector
from scout.connectors.bamboohr import BambooHRConnector
from scout.connectors.rippling import RipplingConnector
from scout.connectors.sage_intacct import SageIntacctConnector
from scout.connectors.netsuite import NetSuiteConnector
from scout.connectors.adp import ADPConnector
from scout.connectors.ukg import UKGConnector
from scout.connectors.okta import OktaConnector
from scout.connectors.azure_ad import AzureADConnector
from scout.connectors.sap import SAPConnector
from scout.connectors.oracle_erp import OracleERPConnector
from scout.connectors.dynamics_365 import Dynamics365Connector
from scout.connectors.dynamics_crm import DynamicsCRMConnector
from scout.connectors.zoho import ZohoConnector
from scout.connectors.servicenow import ServiceNowConnector
from scout.connectors.jira import JiraConnector
from scout.connectors.zendesk import ZendeskConnector
from scout.connectors.freshservice import FreshserviceConnector
from scout.connectors.ramp import RampConnector
from scout.connectors.brex import BrexConnector
from scout.connectors.coupa import CoupaConnector
from scout.connectors.concur import ConcurConnector
from scout.connectors.billcom import BillcomConnector
from scout.connectors.google_workspace import GoogleWorkspaceConnector
from scout.connectors.jumpcloud import JumpCloudConnector
from scout.connectors.quickbooks import QuickBooksConnector
from scout.connectors.gusto import GustoConnector
from scout.connectors.pipedrive import PipedriveConnector
# Sprint 38: Acumatica, Epicor, Dynamics 365 Finance
from scout.connectors.acumatica import AcumaticaConnector
from scout.connectors.epicor import EpicorConnector
from scout.connectors.dynamics_finance import DynamicsFinanceConnector
# Sprint 57: GitHub
from scout.connectors.github import GitHubConnector


def _build_registry() -> dict[str, type[ConnectorBase]]:
    """
    Build the connector registry based on environment.

    Returns a dict mapping connector_id → connector class.
    The class (not an instance) is stored — we instantiate
    per-scan with the appropriate credentials.
    """
    mock_registry = {
        # Core (existing)
        "salesforce":       SalesforceMockConnector,
        "workday":          WorkdayMockConnector,
        "netsuite":         NetsuiteMockConnector,
        # HCM
        "bamboohr":         BambooHRMockConnector,
        "adp":              ADPMockConnector,
        "rippling":         RipplingMockConnector,
        "ukg":              UKGMockConnector,
        "gusto":            GustoMockConnector,
        # CRM
        "hubspot":          HubSpotMockConnector,
        "dynamics_crm":     DynamicsCRMMockConnector,
        "pipedrive":        PipedriveMockConnector,
        "zoho":             ZohoMockConnector,
        # ERP
        "quickbooks":       QuickBooksMockConnector,
        "sap":              SAPMockConnector,
        "dynamics_finance": DynamicsFinanceMockConnector,
        "sage_intacct":     SageIntacctMockConnector,
        "acumatica":        AcumaticaMockConnector,
        "epicor":           EpicorMockConnector,
        # Identity
        "okta":             OktaMockConnector,
        "azure_ad":         AzureADMockConnector,
        "google_workspace": GoogleWorkspaceMockConnector,
        "jumpcloud":        JumpCloudMockConnector,
        # ITSM / SCM
        "servicenow":       ServiceNowMockConnector,
        "jira":             JiraMockConnector,
        "zendesk":          ZendeskMockConnector,
        "freshservice":     FreshserviceMockConnector,
        "github":           GitHubMockConnector,
        # Finance / Spend
        "coupa":            CoupaMockConnector,
        "ramp":             RampMockConnector,
        "brex":             BrexMockConnector,
        "concur":           ConcurMockConnector,
        "billcom":          BillcomMockConnector,
    }

    if settings.use_mock_connectors:
        return mock_registry
    else:
        # Sprint 12: real connectors are live. Override mock entries with
        # production implementations for the connectors that are ready.
        # Remaining connectors continue using mocks as fallback.
        real_overrides: dict[str, type[ConnectorBase]] = {
            # Sprint 12
            "salesforce":   SalesforceConnector,
            "hubspot":      HubSpotConnector,
            "workday":      WorkdayConnector,
            "clearbit":     ClearbitConnector,
            "zoominfo":     ZoomInfoConnector,
            # Sprint 29
            "bamboohr":     BambooHRConnector,
            "rippling":     RipplingConnector,
            "sage_intacct": SageIntacctConnector,
            "netsuite":     NetSuiteConnector,
            # Sprint 30
            "adp":          ADPConnector,
            "ukg":          UKGConnector,
            # Sprint 31
            "okta":           OktaConnector,
            "azure_ad":       AzureADConnector,
            # Sprint 32
            "sap":            SAPConnector,
            "oracle_erp":     OracleERPConnector,
            "dynamics_365":   Dynamics365Connector,
            # Sprint 33
            "dynamics_crm":   DynamicsCRMConnector,
            "zoho":           ZohoConnector,
            # Sprint 34
            "servicenow":     ServiceNowConnector,
            "jira":           JiraConnector,
            # Sprint 35
            "zendesk":        ZendeskConnector,
            "freshservice":   FreshserviceConnector,
            # Sprint 36
            "ramp":             RampConnector,
            "brex":             BrexConnector,
            "coupa":            CoupaConnector,
            # Sprint 37
            "concur":           ConcurConnector,
            "billcom":          BillcomConnector,
            "google_workspace": GoogleWorkspaceConnector,
            "jumpcloud":        JumpCloudConnector,
            "quickbooks":       QuickBooksConnector,
            "gusto":            GustoConnector,
            "pipedrive":        PipedriveConnector,
            # Sprint 38
            "acumatica":        AcumaticaConnector,
            "epicor":           EpicorConnector,
            "dynamics_finance": DynamicsFinanceConnector,
            # Sprint 57
            "github":           GitHubConnector,
        }
        return {**mock_registry, **real_overrides}


# Module-level registry — built once at startup
CONNECTOR_REGISTRY: dict[str, type[ConnectorBase]] = _build_registry()


def get_connector(connector_id: str, credentials: ConnectorCredentials) -> ConnectorBase:
    """
    Instantiate and return a connector for the given connector_id.

    Args:
        connector_id: e.g. "salesforce", "workday", "netsuite"
        credentials:  auth data for this connector + tenant

    Returns:
        A ready-to-use connector instance.

    Raises:
        ValueError if the connector_id is not registered.

    Usage:
        creds = ConnectorCredentials(connector_id="workday", tenant_id="acme", auth_data={})
        connector = get_connector("workday", creds)
        connector.authenticate()
        for record in connector.extract_full("worker"):
            process(record)
    """
    connector_class = CONNECTOR_REGISTRY.get(connector_id)
    if not connector_class:
        available = list(CONNECTOR_REGISTRY.keys())
        raise ValueError(
            f"Unknown connector: '{connector_id}'. "
            f"Available connectors: {available}"
        )
    return connector_class(credentials)


def get_connector_with_stored_creds(
    connector_id: str,
    tenant_id: str,
    db,  # Session — typed loosely to avoid circular import
) -> ConnectorBase | None:
    """
    Sprint 83 — Return a connector instance using credentials stored in
    ConnectorCredentialStore.

    If active credentials exist for (connector_id, tenant_id), builds a real
    ConnectorCredentials object from the stored auth_data and returns the
    appropriate connector (real implementation if registered, mock otherwise).

    If no credentials are found, returns None so the caller can fall back
    to the mock or skip the scan.

    Args:
        connector_id: e.g. "salesforce"
        tenant_id:    the tenant whose credentials to look up
        db:           an open SQLAlchemy Session

    Returns:
        A ConnectorBase instance, or None if no stored credentials exist.
    """
    from scout.db.models import ConnectorCredentialStore  # avoid circular import

    row = (
        db.query(ConnectorCredentialStore)
        .filter_by(tenant_id=tenant_id, connector_id=connector_id, is_active=True)
        .first()
    )
    if not row:
        return None

    creds = ConnectorCredentials(
        connector_id=connector_id,
        tenant_id=tenant_id,
        auth_data=row.auth_data,
    )
    return get_connector(connector_id, creds)


def list_connectors() -> list[dict]:
    """Return a summary of all registered connectors."""
    return [
        {
            "connector_id": cls.CONNECTOR_ID,
            "display_name": cls.DISPLAY_NAME,
            "category": cls.CATEGORY,
            "is_mock": settings.use_mock_connectors,
        }
        for cls in CONNECTOR_REGISTRY.values()
    ]
