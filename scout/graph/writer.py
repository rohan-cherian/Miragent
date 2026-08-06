"""
scout/graph/writer.py — Writes canonical entities into Neo4j.

The writer's job is simple: take canonical entities and upsert them
into the graph. It doesn't care where data came from — that's the
normalizer and resolver's job.

KEY PATTERN: MERGE + SET +=
    MERGE finds or creates a node by its unique key.
    SET p += $props updates properties WITHOUT overwriting unlisted ones.
    Together they form an idempotent UPSERT.

    WRONG:  CREATE (p:Person {canonical_id: $id, email: $email, ...})
            → Creates a duplicate every run

    RIGHT:  MERGE (p:Person {canonical_id: $id})
            SET p += $props
            → Creates on first run, updates on subsequent runs

This means you can run the scanner every day and the graph stays
clean — no duplicates, just freshly updated properties.
"""

import logging
from dataclasses import dataclass, field

from neo4j import Driver

from scout.graph.models import CanonicalAccount, CanonicalOpportunity, CanonicalPerson, CanonicalVendor

logger = logging.getLogger(__name__)


@dataclass
class WriteStats:
    """Counts of nodes and relationships written in one pipeline run."""
    persons_merged: int = 0
    vendors_merged: int = 0
    accounts_merged: int = 0
    opportunities_merged: int = 0
    manages_relationships: int = 0    # Person -[:MANAGES]-> Person
    owns_relationships: int = 0       # Person -[:OWNS]-> Account
    owns_deal_relationships: int = 0  # Person -[:OWNS_DEAL]-> Opportunity
    in_account_relationships: int = 0 # Opportunity -[:IN_ACCOUNT]-> Account

    @property
    def total_nodes(self) -> int:
        return self.persons_merged + self.vendors_merged + self.accounts_merged + self.opportunities_merged

    @property
    def total_relationships(self) -> int:
        return self.manages_relationships + self.owns_relationships + self.owns_deal_relationships + self.in_account_relationships

    def summary(self) -> str:
        return (
            f"Nodes: {self.persons_merged} persons, "
            f"{self.vendors_merged} vendors, "
            f"{self.accounts_merged} accounts | "
            f"Relationships: {self.manages_relationships} MANAGES, "
            f"{self.owns_relationships} OWNS"
        )


class GraphWriter:
    """
    Writes canonical entities and relationships into Neo4j.

    Usage:
        writer = GraphWriter(driver)
        stats = writer.write_all(persons, vendors, accounts)
        print(stats.summary())
    """

    def __init__(self, driver: Driver) -> None:
        self.driver = driver

    # ─────────────────────────────────────────────────────
    # PUBLIC: write everything in one call
    # ─────────────────────────────────────────────────────

    def write_all(
        self,
        persons: list[CanonicalPerson],
        vendors: list[CanonicalVendor],
        accounts: list[CanonicalAccount],
        opportunities: list[CanonicalOpportunity] | None = None,
    ) -> WriteStats:
        """
        Write all entities to Neo4j in the correct order.

        Order matters! We write nodes before relationships.
        A MANAGES relationship requires both Person nodes to exist first.
        """
        stats = WriteStats()

        # Step 1: Write all nodes (no relationships yet)
        logger.info(f"Writing {len(persons)} persons...")
        for person in persons:
            self._merge_person(person)
            stats.persons_merged += 1

        logger.info(f"Writing {len(vendors)} vendors...")
        for vendor in vendors:
            self._merge_vendor(vendor)
            stats.vendors_merged += 1

        logger.info(f"Writing {len(accounts)} accounts...")
        for account in accounts:
            self._merge_account(account)
            stats.accounts_merged += 1

        opps = opportunities or []
        logger.info(f"Writing {len(opps)} opportunities...")
        for opp in opps:
            self._merge_opportunity(opp)
            stats.opportunities_merged += 1

        # Step 2: Write relationships (nodes must exist first)
        logger.info("Writing org hierarchy (MANAGES relationships)...")
        stats.manages_relationships = self._write_manages_relationships(persons)

        logger.info("Writing account ownership (OWNS relationships)...")
        stats.owns_relationships = self._write_owns_relationships(accounts)

        logger.info("Writing deal ownership (OWNS_DEAL relationships)...")
        stats.owns_deal_relationships = self._write_owns_deal_relationships(opps)

        logger.info("Writing deal-to-account (IN_ACCOUNT relationships)...")
        stats.in_account_relationships = self._write_in_account_relationships(opps)

        logger.info(f"Graph write complete: {stats.summary()}")
        return stats

    # ─────────────────────────────────────────────────────
    # NODE WRITERS — one per entity type
    # ─────────────────────────────────────────────────────

    def _merge_person(self, person: CanonicalPerson) -> None:
        """
        Upsert a Person node.

        Cypher breakdown:
          MERGE (p:Person {canonical_id: $id})
            → Find the node with this canonical_id, or create it

          ON CREATE SET p.created_at = $now
            → Only set created_at when first creating the node

          SET p += $props
            → Update all other properties on every run
            → += means "merge into existing" — won't erase unlisted props
        """
        query = """
        MERGE (p:Person {canonical_id: $id})
        ON CREATE SET p.created_at = $now
        SET p += $props
        """
        with self.driver.session() as session:
            session.run(
                query,
                id=person.canonical_id,
                now=person.created_at.isoformat(),
                props=person.to_neo4j_props(),
            )

    def _merge_vendor(self, vendor: CanonicalVendor) -> None:
        """Upsert a Vendor node."""
        query = """
        MERGE (v:Vendor {canonical_id: $id})
        ON CREATE SET v.created_at = $now
        SET v += $props
        """
        with self.driver.session() as session:
            session.run(
                query,
                id=vendor.canonical_id,
                now=vendor.created_at.isoformat(),
                props=vendor.to_neo4j_props(),
            )

    def _merge_account(self, account: CanonicalAccount) -> None:
        """Upsert an Account node."""
        query = """
        MERGE (a:Account {canonical_id: $id})
        ON CREATE SET a.created_at = $now
        SET a += $props
        """
        with self.driver.session() as session:
            session.run(
                query,
                id=account.canonical_id,
                now=account.created_at.isoformat(),
                props=account.to_neo4j_props(),
            )

    # ─────────────────────────────────────────────────────
    # RELATIONSHIP WRITERS
    # ─────────────────────────────────────────────────────

    def _write_manages_relationships(self, persons: list[CanonicalPerson]) -> int:
        """
        Create MANAGES relationships from the org hierarchy.

        For every person who has a manager_canonical_id:
          MATCH the manager node
          MATCH the report node
          MERGE the -[:MANAGES]-> relationship

        The MERGE on relationships is just as important as on nodes —
        running the scanner daily won't create duplicate edges.

        Cypher breakdown:
          MATCH (mgr:Person {canonical_id: $manager_id})
            → Find the manager node (must already exist)
          MATCH (rep:Person {canonical_id: $report_id})
            → Find the direct report node (must already exist)
          MERGE (mgr)-[:MANAGES]->(rep)
            → Create the edge if it doesn't exist, skip if it does
        """
        query = """
        MATCH (mgr:Person {canonical_id: $manager_id})
        MATCH (rep:Person {canonical_id: $report_id})
        MERGE (mgr)-[:MANAGES]->(rep)
        """
        count = 0
        with self.driver.session() as session:
            for person in persons:
                if person.manager_canonical_id:
                    result = session.run(
                        query,
                        manager_id=person.manager_canonical_id,
                        report_id=person.canonical_id,
                    )
                    # Check if the relationship was actually created
                    summary = result.consume()
                    if summary.counters.relationships_created > 0:
                        count += 1
                    else:
                        count += 1  # merged (already existed)
        return count

    def _write_owns_relationships(self, accounts: list[CanonicalAccount]) -> int:
        """
        Create OWNS relationships from AE → Account.

        In Salesforce, every Account has an OwnerId.
        We resolved that OwnerId to a canonical_id during normalization.
        Now we draw the edge in the graph.
        """
        query = """
        MATCH (p:Person {canonical_id: $owner_id})
        MATCH (a:Account {canonical_id: $account_id})
        MERGE (p)-[:OWNS]->(a)
        """
        count = 0
        with self.driver.session() as session:
            for account in accounts:
                if account.owner_canonical_id:
                    session.run(
                        query,
                        owner_id=account.owner_canonical_id,
                        account_id=account.canonical_id,
                    )
                    count += 1
        return count

    # ─────────────────────────────────────────────────────
    # QUERY HELPERS — read back from the graph for reporting
    # ─────────────────────────────────────────────────────

    def count_nodes(self) -> dict[str, int]:
        """Return node counts per label."""
        query = """
        MATCH (n)
        RETURN labels(n)[0] AS label, count(n) AS count
        ORDER BY count DESC
        """
        with self.driver.session() as session:
            result = session.run(query)
            return {row["label"]: row["count"] for row in result}

    def count_relationships(self) -> dict[str, int]:
        """Return relationship counts per type."""
        query = """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(r) AS count
        ORDER BY count DESC
        """
        with self.driver.session() as session:
            result = session.run(query)
            return {row["rel_type"]: row["count"] for row in result}

    def get_org_hierarchy(self, tenant_id: str) -> list[dict]:
        """
        Return the full org chart as a list of manager → report pairs.

        This is a graph traversal query — something that would be
        extremely complex in SQL but is natural in Cypher.
        """
        query = """
        MATCH (mgr:Person {tenant_id: $tenant_id})-[:MANAGES]->(rep:Person)
        RETURN
            mgr.full_name AS manager,
            mgr.job_title AS manager_title,
            rep.full_name AS report,
            rep.job_title AS report_title,
            rep.department AS department
        ORDER BY mgr.full_name, rep.full_name
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]

    def get_span_of_control(self, tenant_id: str) -> list[dict]:
        """
        Return each manager's direct report count (span of control).

        Span of control analysis:
          < 3 reports → management bloat (too many managers, too few ICs)
          4-7 reports → optimal range
          > 10 reports → overwhelmed manager, quality risk

        This is one query that Miragent's Workforce Intelligence Worker
        runs automatically on every scan.
        """
        query = """
        MATCH (mgr:Person {tenant_id: $tenant_id})-[:MANAGES]->(rep:Person)
        WITH mgr, count(rep) AS direct_reports
        RETURN
            mgr.full_name AS manager,
            mgr.job_title AS title,
            mgr.department AS department,
            direct_reports,
            CASE
                WHEN direct_reports < 3  THEN 'BELOW_OPTIMAL'
                WHEN direct_reports <= 7 THEN 'OPTIMAL'
                ELSE                          'OVERLOADED'
            END AS span_rating
        ORDER BY direct_reports DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]

    def get_vendor_spend_by_category(self, tenant_id: str) -> list[dict]:
        """Return total annual spend grouped by vendor category."""
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id})
        WHERE v.is_active = true
        WITH v.category AS category,
             count(v) AS vendor_count,
             sum(v.annual_spend) AS total_spend
        RETURN category, vendor_count, total_spend
        ORDER BY total_spend DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]

    def _merge_opportunity(self, opp: CanonicalOpportunity) -> None:
        """Upsert an Opportunity node."""
        query = """
        MERGE (o:Opportunity {canonical_id: $id})
        ON CREATE SET o.created_at = $now
        SET o += $props
        SET o.tenant_id = $tenant_id
        """
        with self.driver.session() as session:
            session.run(
                query,
                id=opp.canonical_id,
                tenant_id=opp.tenant_id,
                now=opp.created_at.isoformat(),
                props=opp.to_neo4j_props(),
            )

    def _write_owns_deal_relationships(self, opportunities: list[CanonicalOpportunity]) -> int:
        """Create OWNS_DEAL relationships: Person (AE) → Opportunity."""
        count = 0
        query = """
        MATCH (p:Person {canonical_id: $owner_id})
        MATCH (o:Opportunity {canonical_id: $opp_id})
        MERGE (p)-[:OWNS_DEAL]->(o)
        """
        with self.driver.session() as session:
            for opp in opportunities:
                if opp.owner_canonical_id:
                    session.run(query, owner_id=opp.owner_canonical_id, opp_id=opp.canonical_id)
                    count += 1
        return count

    def _write_in_account_relationships(self, opportunities: list[CanonicalOpportunity]) -> int:
        """Create IN_ACCOUNT relationships: Opportunity → Account."""
        count = 0
        query = """
        MATCH (o:Opportunity {canonical_id: $opp_id})
        MATCH (a:Account {canonical_id: $account_id})
        MERGE (o)-[:IN_ACCOUNT]->(a)
        """
        with self.driver.session() as session:
            for opp in opportunities:
                if opp.account_canonical_id:
                    session.run(query, opp_id=opp.canonical_id, account_id=opp.account_canonical_id)
                    count += 1
        return count

    # ── Revenue Intelligence queries ──────────────────────────────────

    def get_open_pipeline(self, tenant_id: str) -> list[dict]:
        """Return all open opportunities with owner info."""
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        OPTIONAL MATCH (p:Person)-[:OWNS_DEAL]->(o)
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.name AS deal_name,
            o.stage AS stage,
            o.amount AS amount,
            o.close_date AS close_date,
            o.probability AS probability,
            o.days_in_pipeline AS days_in_pipeline,
            p.full_name AS owner,
            p.canonical_id AS owner_id,
            a.name AS account_name,
            a.industry AS industry
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]

    def get_won_opportunities(self, tenant_id: str) -> list[dict]:
        """Return closed-won opportunities for expansion / pricing analysis."""
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.name AS deal_name,
            o.amount AS amount,
            o.close_date AS close_date,
            a.name AS account_name,
            a.industry AS industry,
            a.account_type AS account_type
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]

    def get_sales_rep_pipeline(self, tenant_id: str) -> list[dict]:
        """Return open pipeline aggregated per sales rep."""
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: true})
        WHERE p.department = 'Sales'
        OPTIONAL MATCH (p)-[:OWNS_DEAL]->(o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        RETURN
            p.full_name AS rep,
            p.job_title AS title,
            p.canonical_id AS rep_id,
            count(o) AS open_deals,
            coalesce(sum(o.amount), 0) AS pipeline_value,
            coalesce(avg(o.probability), 0) AS avg_probability
        ORDER BY pipeline_value DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]

    def get_upcoming_renewals(self, tenant_id: str, within_days: int = 180) -> list[dict]:
        """
        Return vendors with contract renewals in the next N days.
        This powers the Vendor Intelligence Worker's negotiation timing.
        """
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id})
        WHERE v.contract_renewal IS NOT NULL
          AND v.is_active = true
          AND date(v.contract_renewal) <= date() + duration({days: $days})
          AND date(v.contract_renewal) >= date()
        RETURN
            v.name AS vendor,
            v.category AS category,
            v.annual_spend AS annual_spend,
            v.contract_renewal AS renewal_date,
            v.primary_contact AS contact,
            duration.between(date(), date(v.contract_renewal)).days AS days_until_renewal
        ORDER BY days_until_renewal ASC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, days=within_days)
            return [dict(row) for row in result]
