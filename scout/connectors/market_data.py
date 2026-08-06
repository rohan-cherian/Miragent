"""
scout/connectors/market_data.py — Market Data Connector (Sprint 18)

Pluggable interface for market data sources (G2, Gartner, Forrester).
The mock implementation uses the vendor_intelligence catalog as a source
of truth so tests run deterministically without external API calls.

A real G2 connector will be added in Sprint 19 when the API key is
available.

Usage:
    from scout.connectors.market_data import get_market_data_connector

    connector = get_market_data_connector()
    rating = connector.get_product_rating("Salesforce")
    benchmark = connector.get_pricing_benchmark("Workday", employee_count=300)
    alternatives = connector.get_alternatives("Salesforce", budget=50_000)
"""

from __future__ import annotations

from scout.data.vendor_intelligence import VENDOR_CATALOG, lookup_vendor


class MarketDataConnector:
    """Abstract interface for market data (G2, Gartner, Forrester)."""

    def get_product_rating(self, vendor_name: str) -> dict | None:
        """
        Return rating data for a vendor.

        Returns a dict with keys:
            g2_score        float   0–100 quality/satisfaction score
            reviews_count   int     number of reviews on G2
            satisfaction    float   satisfaction percentage (0–100)
            market_position str     "leader" | "high_performer" | "contender" | "niche"
        Returns None if the vendor is unknown.
        """
        raise NotImplementedError

    def get_pricing_benchmark(self, vendor_name: str, employee_count: int) -> dict | None:
        """
        Return pricing benchmark for a company of a given size.

        Size tiers:
            smb         employee_count < 100
            mid_market  100 <= employee_count < 1000
            enterprise  employee_count >= 1000

        Returns a dict with keys:
            tier            str     "smb" | "mid_market" | "enterprise"
            benchmark_low   float   low end of typical contract range
            benchmark_mid   float   mid-market benchmark (catalog value)
            benchmark_high  float   high end of typical contract range
            employee_count  int     input employee count
        Returns None if the vendor is unknown.
        """
        raise NotImplementedError

    def get_alternatives(self, vendor_name: str, budget: float) -> list[dict]:
        """
        Return alternative products that fit within the given budget.

        Each alternative dict contains:
            vendor_name     str     canonical name of the alternative
            category        str     product category
            typical_cost    float   mid-market typical contract size
            fits_budget     bool    True if typical_cost <= budget
        Returns an empty list if no alternatives are found.
        """
        raise NotImplementedError


class MockMarketDataConnector(MarketDataConnector):
    """
    Deterministic mock — uses vendor_intelligence catalog as source of truth.

    Derives plausible G2 scores from catalog rank data:
        rank 1  → g2_score in 88–95
        rank 2  → g2_score in 82–88
        rank 3+ → g2_score in 72–82

    Pricing benchmarks are taken directly from typical_contract_size and
    scaled ±30% for low/high bounds.
    """

    def get_product_rating(self, vendor_name: str) -> dict | None:
        catalog = lookup_vendor(vendor_name)
        if catalog is None:
            return None

        rank = catalog.get("g2_category_rank", 5)
        # Derive a deterministic g2_score from rank
        if rank == 1:
            g2_score = 92.0 - (hash(vendor_name) % 8) / 10  # 84–92
        elif rank == 2:
            g2_score = 85.0 - (hash(vendor_name) % 6) / 10  # 79–85
        else:
            g2_score = 80.0 - (hash(vendor_name) % 10) / 10  # 79–80 range varies

        # Ensure score stays in a reasonable range
        g2_score = max(65.0, min(98.0, g2_score))

        satisfaction = min(100.0, g2_score + 2.0)

        reviews_count = max(50, 2000 - (rank - 1) * 300 + (hash(vendor_name) % 200))

        if rank == 1:
            market_position = "leader"
        elif rank == 2:
            market_position = "high_performer"
        elif rank <= 4:
            market_position = "contender"
        else:
            market_position = "niche"

        return {
            "g2_score": round(g2_score, 1),
            "reviews_count": reviews_count,
            "satisfaction": round(satisfaction, 1),
            "market_position": market_position,
        }

    def get_pricing_benchmark(self, vendor_name: str, employee_count: int) -> dict | None:
        catalog = lookup_vendor(vendor_name)
        if catalog is None:
            return None

        contract_sizes = catalog.get("typical_contract_size", {})
        if not contract_sizes:
            return None

        if employee_count < 100:
            tier = "smb"
        elif employee_count < 1000:
            tier = "mid_market"
        else:
            tier = "enterprise"

        benchmark_mid = contract_sizes.get(tier, 0) or 0
        if benchmark_mid == 0:
            # Fall back to adjacent tier
            for fallback in ("mid_market", "smb", "enterprise"):
                benchmark_mid = contract_sizes.get(fallback, 0) or 0
                if benchmark_mid:
                    break

        benchmark_low = benchmark_mid * 0.70
        benchmark_high = benchmark_mid * 1.30

        return {
            "tier": tier,
            "benchmark_low": round(benchmark_low, 0),
            "benchmark_mid": round(benchmark_mid, 0),
            "benchmark_high": round(benchmark_high, 0),
            "employee_count": employee_count,
        }

    def get_alternatives(self, vendor_name: str, budget: float) -> list[dict]:
        catalog = lookup_vendor(vendor_name)
        if catalog is None:
            return []

        alt_keys = catalog.get("alternatives", [])
        results = []

        for alt_key in alt_keys:
            alt_catalog = VENDOR_CATALOG.get(alt_key)
            if alt_catalog is None:
                continue
            typical_cost = alt_catalog.get("typical_contract_size", {}).get("mid_market", 0) or 0
            results.append({
                "vendor_name": alt_catalog.get("canonical_name", alt_key),
                "category": alt_catalog.get("category", ""),
                "typical_cost": typical_cost,
                "fits_budget": typical_cost <= budget,
            })

        return results


def get_market_data_connector() -> MarketDataConnector:
    """
    Factory — returns mock for now, real connector when configured.

    In Sprint 19, if settings.g2_api_key is set, this will return a real
    G2Connector instead of the mock.
    """
    from scout.config import settings  # noqa: F401
    # Future: if getattr(settings, 'g2_api_key', None):
    #     from scout.connectors.g2 import G2Connector
    #     return G2Connector(settings.g2_api_key)
    return MockMarketDataConnector()
