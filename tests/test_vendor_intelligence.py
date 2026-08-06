"""
tests/test_vendor_intelligence.py

Unit tests for the vendor intelligence database.

Run with:  poetry run pytest tests/test_vendor_intelligence.py -v
"""

import pytest

from scout.data.vendor_intelligence import (
    VENDOR_CATALOG,
    REQUIRED_KEYS,
    lookup_vendor,
    get_negotiation_tips,
    get_alternatives,
    get_category_vendors,
)


class TestLookupVendor:

    def test_lookup_known_vendor(self):
        """Salesforce lookup returns a dict with all required keys."""
        result = lookup_vendor("salesforce")
        assert result is not None
        assert isinstance(result, dict)
        for key in REQUIRED_KEYS:
            assert key in result, f"Missing required key: {key}"

    def test_lookup_unknown_vendor_returns_none(self):
        """Unknown vendor name returns None."""
        result = lookup_vendor("totally-unknown-vendor-xyz-12345")
        assert result is None

    def test_lookup_empty_string_returns_none(self):
        """Empty string returns None."""
        result = lookup_vendor("")
        assert result is None

    def test_lookup_case_insensitive_lower(self):
        """Lowercase 'salesforce' works."""
        result = lookup_vendor("salesforce")
        assert result is not None
        assert result["canonical_name"] == "Salesforce"

    def test_lookup_case_insensitive_upper(self):
        """Uppercase 'SALESFORCE' works."""
        result = lookup_vendor("SALESFORCE")
        assert result is not None
        assert result["canonical_name"] == "Salesforce"

    def test_lookup_case_insensitive_mixed(self):
        """Mixed-case 'Salesforce' works."""
        result = lookup_vendor("Salesforce")
        assert result is not None
        assert result["canonical_name"] == "Salesforce"

    def test_lookup_by_fuzzy_name_with_inc(self):
        """'Salesforce Inc' matches 'salesforce'."""
        result = lookup_vendor("Salesforce Inc")
        assert result is not None
        assert result["canonical_name"] == "Salesforce"

    def test_lookup_by_alias_sfdc(self):
        """'SFDC' alias resolves to Salesforce."""
        result = lookup_vendor("sfdc")
        assert result is not None
        assert result["canonical_name"] == "Salesforce"

    def test_lookup_workday(self):
        """Workday lookup works."""
        result = lookup_vendor("workday")
        assert result is not None
        assert result["canonical_name"] == "Workday"

    def test_lookup_workday_inc(self):
        """'Workday Inc' alias works."""
        result = lookup_vendor("Workday Inc")
        assert result is not None
        assert result["canonical_name"] == "Workday"

    def test_lookup_netsuite_alias(self):
        """'Oracle NetSuite' alias resolves to netsuite entry."""
        result = lookup_vendor("Oracle NetSuite")
        assert result is not None
        assert "netsuite" in result["canonical_name"].lower() or result.get("category") == "ERP"

    def test_lookup_slack_technologies(self):
        """'Slack Technologies' alias works."""
        result = lookup_vendor("Slack Technologies")
        assert result is not None
        assert result["canonical_name"] == "Slack"

    def test_lookup_aws(self):
        """'Amazon Web Services' resolves to AWS entry."""
        result = lookup_vendor("Amazon Web Services")
        assert result is not None
        assert result["canonical_name"] == "Amazon Web Services"

    def test_lookup_microsoft_365_variants(self):
        """Various M365 aliases all work."""
        for alias in ["Microsoft 365", "Office 365", "o365", "m365"]:
            result = lookup_vendor(alias)
            assert result is not None, f"Failed for alias: {alias}"

    def test_lookup_google_workspace_alias(self):
        """'G Suite' resolves to Google Workspace."""
        result = lookup_vendor("G Suite")
        assert result is not None
        assert result["canonical_name"] == "Google Workspace"

    def test_lookup_snowflake(self):
        """Snowflake lookup works."""
        result = lookup_vendor("snowflake")
        assert result is not None
        assert result["canonical_name"] == "Snowflake"

    def test_lookup_datadog(self):
        """Datadog lookup works."""
        result = lookup_vendor("datadog")
        assert result is not None
        assert result["canonical_name"] == "Datadog"

    def test_lookup_returns_dict_not_reference(self):
        """Lookup returns the actual dict (not a copy check, just type)."""
        result = lookup_vendor("hubspot")
        assert isinstance(result, dict)


class TestNegotiationTips:

    def test_negotiation_tips_known_vendor_returns_list(self):
        """Known vendor returns a list of strings."""
        tips = get_negotiation_tips("salesforce")
        assert isinstance(tips, list)
        assert len(tips) > 0
        for tip in tips:
            assert isinstance(tip, str)
            assert len(tip) > 0

    def test_negotiation_tips_workday(self):
        """Workday returns specific tips."""
        tips = get_negotiation_tips("workday")
        assert isinstance(tips, list)
        assert len(tips) > 0

    def test_negotiation_tips_unknown_vendor_returns_generic(self):
        """Unknown vendor returns generic tips (not empty)."""
        tips = get_negotiation_tips("completely-unknown-vendor-abc-999")
        assert isinstance(tips, list)
        assert len(tips) > 0
        for tip in tips:
            assert isinstance(tip, str)

    def test_negotiation_tips_case_insensitive(self):
        """Negotiation tips work regardless of case."""
        tips_lower = get_negotiation_tips("salesforce")
        tips_upper = get_negotiation_tips("SALESFORCE")
        assert tips_lower == tips_upper

    def test_negotiation_tips_alias(self):
        """'Salesforce Inc' returns same tips as 'salesforce'."""
        tips_alias = get_negotiation_tips("Salesforce Inc")
        tips_direct = get_negotiation_tips("salesforce")
        assert tips_alias == tips_direct

    def test_negotiation_tips_snowflake_mentions_discount(self):
        """Snowflake tips mention credits or discount (consumption-based specifics)."""
        tips = get_negotiation_tips("snowflake")
        combined = " ".join(tips).lower()
        assert any(word in combined for word in ["credit", "discount", "commit", "consumption"])


class TestGetAlternatives:

    def test_alternatives_known_vendor_returns_list(self):
        """Known vendor returns a list."""
        alts = get_alternatives("salesforce")
        assert isinstance(alts, list)
        assert len(alts) > 0

    def test_alternatives_salesforce_includes_hubspot(self):
        """Salesforce alternatives include HubSpot."""
        alts = get_alternatives("salesforce")
        assert "hubspot" in alts

    def test_alternatives_hubspot_includes_salesforce(self):
        """HubSpot alternatives include Salesforce."""
        alts = get_alternatives("hubspot")
        assert "salesforce" in alts

    def test_alternatives_unknown_vendor_returns_empty(self):
        """Unknown vendor returns empty list (not None, not exception)."""
        alts = get_alternatives("completely-unknown-vendor-xyz-999")
        assert isinstance(alts, list)
        assert len(alts) == 0

    def test_alternatives_workday(self):
        """Workday has alternatives listed."""
        alts = get_alternatives("workday")
        assert len(alts) > 0

    def test_alternatives_case_insensitive(self):
        """Alternatives work regardless of case."""
        alts_lower = get_alternatives("salesforce")
        alts_upper = get_alternatives("SALESFORCE")
        assert alts_lower == alts_upper


class TestGetCategoryVendors:

    def test_get_category_vendors_crm_returns_salesforce_and_hubspot(self):
        """CRM category returns at least Salesforce and HubSpot."""
        vendors = get_category_vendors("CRM")
        assert "salesforce" in vendors
        assert "hubspot" in vendors

    def test_get_category_vendors_hris_returns_workday(self):
        """HRIS category includes Workday."""
        vendors = get_category_vendors("HRIS")
        assert "workday" in vendors
        assert "bamboohr" in vendors

    def test_get_category_vendors_case_insensitive(self):
        """Category lookup is case-insensitive."""
        vendors_upper = get_category_vendors("CRM")
        vendors_lower = get_category_vendors("crm")
        assert set(vendors_upper) == set(vendors_lower)

    def test_get_category_vendors_analytics(self):
        """Analytics category includes Tableau and Looker."""
        vendors = get_category_vendors("Analytics")
        assert "tableau" in vendors
        assert "looker" in vendors

    def test_get_category_vendors_security(self):
        """Security category includes Okta and CrowdStrike."""
        vendors = get_category_vendors("Security")
        assert "okta" in vendors
        assert "crowdstrike" in vendors

    def test_get_category_vendors_unknown_returns_empty(self):
        """Unknown category returns empty list."""
        vendors = get_category_vendors("XYZ-NONEXISTENT-CATEGORY-999")
        assert isinstance(vendors, list)
        assert len(vendors) == 0

    def test_get_category_vendors_returns_list(self):
        """Returns a list (not None, not dict)."""
        result = get_category_vendors("CRM")
        assert isinstance(result, list)


class TestCatalogIntegrity:

    def test_all_entries_have_required_keys(self):
        """Every VENDOR_CATALOG entry has all required keys."""
        missing = {}
        for vendor_key, entry in VENDOR_CATALOG.items():
            missing_keys = REQUIRED_KEYS - entry.keys()
            if missing_keys:
                missing[vendor_key] = missing_keys

        assert not missing, (
            f"Vendors missing required keys: "
            + ", ".join(f"{k}: {v}" for k, v in missing.items())
        )

    def test_all_canonical_names_are_strings(self):
        """canonical_name is a non-empty string for all entries."""
        for key, entry in VENDOR_CATALOG.items():
            assert isinstance(entry["canonical_name"], str), f"Bad canonical_name for {key}"
            assert len(entry["canonical_name"]) > 0, f"Empty canonical_name for {key}"

    def test_all_categories_are_strings(self):
        """category is a non-empty string for all entries."""
        for key, entry in VENDOR_CATALOG.items():
            assert isinstance(entry["category"], str), f"Bad category for {key}"
            assert len(entry["category"]) > 0, f"Empty category for {key}"

    def test_all_alternatives_are_lists(self):
        """alternatives is a list for all entries."""
        for key, entry in VENDOR_CATALOG.items():
            assert isinstance(entry["alternatives"], list), f"Bad alternatives for {key}"

    def test_all_negotiation_leverage_are_lists_of_strings(self):
        """negotiation_leverage is a list of strings for all entries."""
        for key, entry in VENDOR_CATALOG.items():
            leverage = entry["negotiation_leverage"]
            assert isinstance(leverage, list), f"Bad negotiation_leverage type for {key}"
            assert len(leverage) > 0, f"Empty negotiation_leverage for {key}"
            for item in leverage:
                assert isinstance(item, str), f"Non-string in negotiation_leverage for {key}"

    def test_catalog_has_minimum_size(self):
        """Catalog contains at least 50 vendors."""
        assert len(VENDOR_CATALOG) >= 50, f"Expected >=50 vendors, got {len(VENDOR_CATALOG)}"

    def test_catalog_contains_expected_vendors(self):
        """Spot-check that key vendors are present in the catalog."""
        expected = [
            "salesforce", "hubspot", "workday", "bamboohr", "netsuite",
            "sage-intacct", "tableau", "looker", "snowflake", "databricks",
            "microsoft-365", "google-workspace", "slack", "zoom", "okta",
            "crowdstrike", "qualys", "github", "jira", "confluence",
            "datadog", "pagerduty", "marketo", "pardot", "outreach",
            "salesloft", "zoominfo", "clearbit", "expensify", "coupa",
            "brex", "ramp", "gusto", "rippling", "lattice",
            "culture-amp", "greenhouse", "lever", "gainsight", "churnzero",
            "zendesk", "intercom", "gong", "chorus", "docusign",
            "ironclad", "notion", "asana", "monday-com", "figma",
            "miro", "aws", "azure", "gcp", "cloudflare",
            "fastly", "twilio", "segment", "amplitude",
        ]
        missing = [v for v in expected if v not in VENDOR_CATALOG]
        assert not missing, f"Missing expected vendors: {missing}"

    def test_pricing_models_are_strings(self):
        """pricing_model is a non-empty string for all entries."""
        for key, entry in VENDOR_CATALOG.items():
            pm = entry.get("pricing_model")
            assert isinstance(pm, str), f"Bad pricing_model for {key}"
            assert len(pm) > 0, f"Empty pricing_model for {key}"

    def test_no_duplicate_canonical_names(self):
        """No two entries share the same canonical_name."""
        seen: dict[str, str] = {}
        for key, entry in VENDOR_CATALOG.items():
            cn = entry["canonical_name"]
            assert cn not in seen, (
                f"Duplicate canonical_name '{cn}' in keys '{seen[cn]}' and '{key}'"
            )
            seen[cn] = key
