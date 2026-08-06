"""
scout/graph/schema.py — Neo4j schema initialisation.

Creates all constraints and indexes needed by Scout.
Run once at startup (idempotent — safe to run multiple times).

CONSTRAINTS vs INDEXES:
  Constraint = a rule that Neo4j ENFORCES.
    "No two :Person nodes can share the same canonical_id"
    If you try to create a duplicate, Neo4j raises an error.
    Also automatically creates an index on the constrained property.

  Index = a speedup for queries that Neo4j does NOT enforce.
    "Make MATCH (p:Person {email: $email}) fast"
    Without it, Neo4j scans every Person node — slow at scale.

Run with:
    from scout.graph.schema import init_schema
    init_schema(driver)
"""

from neo4j import Driver
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# CONSTRAINTS — uniqueness guarantees
# IF NOT EXISTS makes these idempotent (safe to re-run)
# ─────────────────────────────────────────────────────────
CONSTRAINTS = [
    # Person: canonical_id is the primary key (encodes tenant_id + email hash)
    "CREATE CONSTRAINT person_canonical_id IF NOT EXISTS FOR (p:Person) REQUIRE p.canonical_id IS UNIQUE",
    # Person: composite (tenant_id, email) uniqueness — multi-tenant safe
    # The same email can exist in two different tenants; it cannot appear twice
    # within the same tenant. canonical_id already encodes this, but the
    # composite constraint gives Neo4j a fast lookup path and a safety net.
    "CREATE CONSTRAINT person_tenant_email IF NOT EXISTS FOR (p:Person) REQUIRE (p.tenant_id, p.email) IS UNIQUE",
    # Vendor: canonical_id is the primary key
    "CREATE CONSTRAINT vendor_canonical_id IF NOT EXISTS FOR (v:Vendor) REQUIRE v.canonical_id IS UNIQUE",
    # Account: canonical_id is the primary key
    "CREATE CONSTRAINT account_canonical_id IF NOT EXISTS FOR (a:Account) REQUIRE a.canonical_id IS UNIQUE",
    # Opportunity: canonical_id is the primary key
    "CREATE CONSTRAINT opportunity_canonical_id IF NOT EXISTS FOR (o:Opportunity) REQUIRE o.canonical_id IS UNIQUE",
]

# Constraints from earlier schema versions that must be dropped on migration.
# init_schema() will silently ignore DROP errors (constraint may not exist).
DROPPED_CONSTRAINTS = [
    "DROP CONSTRAINT person_email IF EXISTS",  # replaced by person_tenant_email
]

# ─────────────────────────────────────────────────────────
# INDEXES — query performance
# ─────────────────────────────────────────────────────────
INDEXES = [
    # Person lookups — common query patterns
    "CREATE INDEX person_department IF NOT EXISTS FOR (p:Person) ON (p.department)",
    "CREATE INDEX person_is_active IF NOT EXISTS FOR (p:Person) ON (p.is_active)",
    "CREATE INDEX person_employment_type IF NOT EXISTS FOR (p:Person) ON (p.employment_type)",
    "CREATE INDEX person_tenant IF NOT EXISTS FOR (p:Person) ON (p.tenant_id)",

    # Vendor lookups — Vendor Intelligence Worker queries
    "CREATE INDEX vendor_category IF NOT EXISTS FOR (v:Vendor) ON (v.category)",
    "CREATE INDEX vendor_renewal IF NOT EXISTS FOR (v:Vendor) ON (v.contract_renewal)",
    "CREATE INDEX vendor_spend IF NOT EXISTS FOR (v:Vendor) ON (v.annual_spend)",

    # Account lookups
    "CREATE INDEX account_type IF NOT EXISTS FOR (a:Account) ON (a.account_type)",
    "CREATE INDEX account_industry IF NOT EXISTS FOR (a:Account) ON (a.industry)",

    # Opportunity lookups — Revenue Worker queries
    "CREATE INDEX opportunity_stage IF NOT EXISTS FOR (o:Opportunity) ON (o.stage)",
    "CREATE INDEX opportunity_is_closed IF NOT EXISTS FOR (o:Opportunity) ON (o.is_closed)",
    "CREATE INDEX opportunity_close_date IF NOT EXISTS FOR (o:Opportunity) ON (o.close_date)",
    "CREATE INDEX opportunity_tenant IF NOT EXISTS FOR (o:Opportunity) ON (o.tenant_id)",
]


def init_schema(driver: Driver) -> None:
    """
    Create all constraints and indexes in Neo4j.

    This is idempotent — the IF NOT EXISTS clause means running it
    twice doesn't raise errors or change anything on the second run.

    Also runs any necessary migrations (dropping old constraints).

    Called once at application startup before any data is written.
    """
    with driver.session() as session:
        # Drop obsolete constraints first (migrations)
        for statement in DROPPED_CONSTRAINTS:
            try:
                session.run(statement)
                logger.debug(f"Dropped old constraint: {statement}")
            except Exception:
                pass  # Already gone — that's fine

        for statement in CONSTRAINTS:
            try:
                session.run(statement)
                name = statement.split("IF NOT EXISTS")[0].split()[-1]
                logger.debug(f"Constraint OK: {name}")
            except Exception as e:
                logger.warning(f"Constraint skipped ({e}): {statement[:60]}")

        for statement in INDEXES:
            try:
                session.run(statement)
                name = statement.split("IF NOT EXISTS")[0].split()[-1]
                logger.debug(f"Index OK: {name}")
            except Exception as e:
                logger.warning(f"Index skipped ({e}): {statement[:60]}")

    logger.info(f"Schema initialised: {len(CONSTRAINTS)} constraints, {len(INDEXES)} indexes")
