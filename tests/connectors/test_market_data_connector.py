"""
tests/connectors/test_market_data_connector.py — Tests for MarketDataConnector (Sprint 18)

These tests run with NO external dependencies — no Neo4j, no APIs.
The mock connector uses the vendor_intelligence catalog as the source of truth.

Run with:
    poetry run python -m pytest tests/connectors/test_market_data_connector.py -v
"""

import pytest


class TestMockMarketDataConnectorImport:

    def test_mock_connector_importable(self):
        from scout.connectors.market_data import (  # noqa: F401
            MarketDataConnector,
            MockMarketDataConnector,
            get_market_data_connector,
        )


class TestGetProductRating:

    @pytest.fixture(autouse=True)
    def connector(self):
        from scout.connectors.market_data import MockMarketDataConnector
        self.conn = MockMarketDataConnector()

    def test_get_product_rating_known_vendor(self):
        result = self.conn.get_product_rating("salesforce")
        assert result is not None
        assert "g2_score" in result
        assert "reviews_count" in result
        assert "satisfaction" in result
        assert "market_position" in result

    def test_get_product_rating_known_vendor_values_in_range(self):
        result = self.conn.get_product_rating("salesforce")
        assert 0 <= result["g2_score"] <= 100
        assert result["reviews_count"] > 0
        assert 0 <= result["satisfaction"] <= 100
        assert result["market_position"] in ("leader", "high_performer", "contender", "niche")

    def test_get_product_rating_unknown_vendor_returns_none(self):
        result = self.conn.get_product_rating("completely-unknown-vendor-xyz-12345")
        assert result is None

    def test_get_product_rating_rank1_is_leader(self):
        # Salesforce is rank 1 in CRM
        result = self.conn.get_product_rating("salesforce")
        assert result["market_position"] == "leader"


class TestGetPricingBenchmark:

    @pytest.fixture(autouse=True)
    def connector(self):
        from scout.connectors.market_data import MockMarketDataConnector
        self.conn = MockMarketDataConnector()

    def test_get_pricing_benchmark_mid_market(self):
        result = self.conn.get_pricing_benchmark("salesforce", employee_count=200)
        assert result is not None
        assert result["tier"] == "mid_market"
        assert "benchmark_low" in result
        assert "benchmark_mid" in result
        assert "benchmark_high" in result
        assert result["employee_count"] == 200

    def test_get_pricing_benchmark_enterprise(self):
        result = self.conn.get_pricing_benchmark("workday", employee_count=1500)
        assert result is not None
        assert result["tier"] == "enterprise"
        assert result["benchmark_mid"] > 0

    def test_get_pricing_benchmark_smb(self):
        result = self.conn.get_pricing_benchmark("hubspot", employee_count=50)
        assert result is not None
        assert result["tier"] == "smb"

    def test_get_pricing_benchmark_unknown_vendor(self):
        result = self.conn.get_pricing_benchmark("completely-unknown-xyz", employee_count=200)
        assert result is None

    def test_get_pricing_benchmark_low_lt_mid_lt_high(self):
        result = self.conn.get_pricing_benchmark("salesforce", employee_count=500)
        assert result["benchmark_low"] < result["benchmark_mid"] < result["benchmark_high"]


class TestGetAlternatives:

    @pytest.fixture(autouse=True)
    def connector(self):
        from scout.connectors.market_data import MockMarketDataConnector
        self.conn = MockMarketDataConnector()

    def test_get_alternatives_returns_list(self):
        result = self.conn.get_alternatives("salesforce", budget=50_000)
        assert isinstance(result, list)

    def test_get_alternatives_known_vendor_has_entries(self):
        result = self.conn.get_alternatives("salesforce", budget=999_999)
        assert len(result) > 0

    def test_get_alternatives_dict_has_required_keys(self):
        result = self.conn.get_alternatives("salesforce", budget=999_999)
        for alt in result:
            assert "vendor_name" in alt
            assert "category" in alt
            assert "typical_cost" in alt
            assert "fits_budget" in alt

    def test_get_alternatives_fits_budget_flag(self):
        # Budget of $1 means nothing fits
        result = self.conn.get_alternatives("salesforce", budget=1.0)
        for alt in result:
            if alt["typical_cost"] > 1.0:
                assert alt["fits_budget"] is False

    def test_get_alternatives_unknown_vendor_returns_empty(self):
        result = self.conn.get_alternatives("completely-unknown-xyz", budget=100_000)
        assert result == []


class TestGetMarketDataConnectorFactory:

    def test_get_market_data_connector_returns_mock(self):
        from scout.connectors.market_data import (
            MockMarketDataConnector,
            get_market_data_connector,
        )
        connector = get_market_data_connector()
        assert isinstance(connector, MockMarketDataConnector)

    def test_factory_connector_is_usable(self):
        from scout.connectors.market_data import get_market_data_connector
        connector = get_market_data_connector()
        result = connector.get_product_rating("salesforce")
        assert result is not None
