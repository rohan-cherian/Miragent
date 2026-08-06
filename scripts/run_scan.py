"""
scripts/run_scan.py — Run a full Scout scan and display the digital twin.

This script runs the complete pipeline and then queries the graph
to show you what was built. This is the payoff of Sprint 1.

Usage:
    poetry run python scripts/run_scan.py
"""

import logging
import sys

# Suppress info logs during the scan for cleaner output
logging.basicConfig(level=logging.WARNING)

from scout.ingestion.pipeline import IngestionPipeline
from neo4j import GraphDatabase
from scout.config import settings


def run():
    TENANT_ID = settings.tenant_id

    print()
    print("━" * 55)
    print("  Miragent Scout — Digital Twin Builder")
    print(f"  Tenant: {TENANT_ID}")
    print("━" * 55)
    print()
    print("  Running ingestion pipeline...")
    print()

    # ── Run the pipeline ──────────────────────────────────
    pipeline = IngestionPipeline()
    result = pipeline.run(tenant_id=TENANT_ID)
    result.print_summary()

    # ── Query the graph ───────────────────────────────────
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    writer = pipeline.writer

    # ── 1. Org Hierarchy ──────────────────────────────────
    print("━" * 55)
    print("  ORG HIERARCHY  (MANAGES relationships in graph)")
    print("━" * 55)
    hierarchy = writer.get_org_hierarchy(TENANT_ID)
    # Group by manager
    from collections import defaultdict
    by_manager = defaultdict(list)
    for row in hierarchy:
        by_manager[f"{row['manager']} ({row['manager_title']})"].append(
            f"{row['report']}  [{row['report_title']}]"
        )
    for manager, reports in sorted(by_manager.items()):
        print(f"\n  {manager}")
        for r in reports:
            print(f"    └── {r}")
    print()

    # ── 2. Span of Control ────────────────────────────────
    print("━" * 55)
    print("  SPAN OF CONTROL  (Workforce Intelligence Worker)")
    print("━" * 55)
    print(f"  {'Manager':<22} {'Title':<25} {'Reports':>7}  {'Rating'}")
    print(f"  {'─'*22} {'─'*25} {'─'*7}  {'─'*15}")
    for row in writer.get_span_of_control(TENANT_ID):
        icon = {"OPTIMAL": "✅", "BELOW_OPTIMAL": "⚠️ ", "OVERLOADED": "🔴"}.get(row["span_rating"], "")
        print(f"  {row['manager']:<22} {(row['title'] or ''):<25} {row['direct_reports']:>7}  {icon} {row['span_rating']}")
    print()

    # ── 3. Vendor Spend ───────────────────────────────────
    print("━" * 55)
    print("  VENDOR SPEND BY CATEGORY  (Vendor Intelligence Worker)")
    print("━" * 55)
    print(f"  {'Category':<25} {'Vendors':>7}  {'Annual Spend':>15}")
    print(f"  {'─'*25} {'─'*7}  {'─'*15}")
    for row in writer.get_vendor_spend_by_category(TENANT_ID):
        spend = f"${row['total_spend']:,.0f}"
        print(f"  {(row['category'] or 'Unknown'):<25} {row['vendor_count']:>7}  {spend:>15}")
    print()

    # ── 4. Upcoming Renewals ──────────────────────────────
    print("━" * 55)
    print("  CONTRACT RENEWALS  (next 180 days)")
    print("━" * 55)
    renewals = writer.get_upcoming_renewals(TENANT_ID, within_days=180)
    if renewals:
        print(f"  {'Vendor':<25} {'Renewal':<12} {'Days':>5}  {'Spend':>12}")
        print(f"  {'─'*25} {'─'*12} {'─'*5}  {'─'*12}")
        for row in renewals:
            spend = f"${row['annual_spend']:,.0f}"
            days = row.get("days_until_renewal", "?")
            print(f"  {row['vendor']:<25} {row['renewal_date']:<12} {str(days):>5}  {spend:>12}")
    else:
        print("  No renewals in the next 180 days.")
    print()

    # ── 5. Cross-system people ────────────────────────────
    print("━" * 55)
    print("  PEOPLE IN BOTH WORKDAY + SALESFORCE")
    print("━" * 55)
    with driver.session() as session:
        result_q = session.run("""
            MATCH (p:Person {tenant_id: $tid})
            WHERE p.workday_id IS NOT NULL AND p.salesforce_id IS NOT NULL
            RETURN p.full_name AS name, p.job_title AS title,
                   p.department AS dept, p.workday_id AS wd_id,
                   p.salesforce_id AS sfdc_id,
                   p.source_systems AS sources
            ORDER BY p.full_name
        """, tid=TENANT_ID)
        rows = list(result_q)

    print(f"  {'Name':<20} {'Title':<25} {'Systems'}")
    print(f"  {'─'*20} {'─'*25} {'─'*20}")
    for row in rows:
        sources = " + ".join(row["sources"])
        print(f"  {row['name']:<20} {(row['title'] or ''):<25} {sources}")
    print()

    # ── 6. Graph totals ───────────────────────────────────
    print("━" * 55)
    node_counts = writer.count_nodes()
    rel_counts = writer.count_relationships()
    total_nodes = sum(node_counts.values())
    total_rels = sum(rel_counts.values())
    print(f"  GRAPH TOTALS: {total_nodes} nodes, {total_rels} relationships")
    for label, count in node_counts.items():
        print(f"    :{label}  →  {count} nodes")
    for rel, count in rel_counts.items():
        print(f"    [{rel}]  →  {count} relationships")
    print()
    print("  🚀 Digital twin built. Open Neo4j Browser to explore:")
    print("     http://localhost:7474  (neo4j / miragent_dev)")
    print()
    print("  Try this Cypher query in the browser:")
    print("     MATCH (p:Person)-[:MANAGES]->(r:Person)")
    print("     RETURN p, r  LIMIT 25")
    print()
    print("━" * 55)
    print()

    driver.close()
    pipeline.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"\n  ❌ Error: {e}")
        raise
