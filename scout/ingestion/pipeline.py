"""
scout/ingestion/pipeline.py — The ingestion pipeline orchestrator.

Coordinates the full flow from connectors to graph:

  EXTRACT    — pull RawRecords from all connectors
      ↓
  NORMALIZE  — translate raw API fields to canonical vocabulary
      ↓
  RESOLVE    — merge duplicates into canonical entities
      ↓
  WRITE      — upsert canonical entities into Neo4j

The pipeline is the conductor — it calls each stage in sequence
but doesn't implement any of them. Each stage is independently
testable and can be swapped without changing the pipeline.

This pattern is called a DATA PIPELINE or ETL PIPELINE.
It's the backbone of every serious data engineering system.
"""

import logging
import time
from dataclasses import dataclass, field

from neo4j import GraphDatabase

from scout.config import settings
from scout.connectors.models import ConnectorCredentials, RawRecord
from scout.connectors.registry import get_connector, list_connectors
from scout.graph.schema import init_schema
from scout.graph.writer import GraphWriter, WriteStats
from scout.ingestion.normalizer import normalize
from scout.ingestion.resolver import EntityResolver

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Summary of a completed pipeline run."""
    tenant_id: str
    connectors_run: list[str] = field(default_factory=list)
    records_extracted: int = 0
    records_normalized: int = 0
    records_skipped: int = 0
    write_stats: WriteStats | None = None
    # Resolved entity counts — populated even when Neo4j write fails
    persons_resolved: int = 0
    vendors_resolved: int = 0
    accounts_resolved: int = 0
    opportunities_resolved: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def print_summary(self) -> None:
        """Print a human-readable summary to stdout."""
        w = self.write_stats

        print()
        print("━" * 55)
        print("  Scout Ingestion Pipeline — Results")
        print("━" * 55)
        print()
        print(f"  Tenant:    {self.tenant_id}")
        print(f"  Duration:  {self.duration_seconds:.1f}s")
        print()
        print("  EXTRACTION")
        print(f"    Connectors run:    {', '.join(self.connectors_run)}")
        print(f"    Records extracted: {self.records_extracted}")
        print(f"    Records normalized:{self.records_normalized}")
        print(f"    Records skipped:   {self.records_skipped}")
        print()
        if w:
            print("  GRAPH WRITE")
            print(f"    Person nodes:   {w.persons_merged}")
            print(f"    Vendor nodes:   {w.vendors_merged}")
            print(f"    Account nodes:  {w.accounts_merged}")
            print(f"    MANAGES edges:  {w.manages_relationships}")
            print(f"    OWNS edges:     {w.owns_relationships}")
        print()
        if self.errors:
            print(f"  ERRORS ({len(self.errors)})")
            for err in self.errors:
                print(f"    ⚠️  {err}")
            print()
        print("━" * 55)
        print()


class IngestionPipeline:
    """
    The Scout ingestion pipeline.

    Connects to all registered connectors, extracts data,
    normalizes and resolves it, then writes to Neo4j.

    Usage:
        pipeline = IngestionPipeline()
        result = pipeline.run(tenant_id="acme-corp")
        result.print_summary()
    """

    def __init__(self) -> None:
        self.neo4j_driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        self.writer = GraphWriter(self.neo4j_driver)

    def run(self, tenant_id: str) -> PipelineResult:
        """
        Execute the full pipeline for a tenant.

        Stages:
          1. Schema init  — ensure Neo4j constraints/indexes exist
          2. Extract      — pull from all connectors
          3. Normalize    — translate to canonical vocabulary
          4. Resolve      — deduplicate into canonical entities
          5. Write        — upsert into Neo4j
        """
        start = time.time()
        result = PipelineResult(tenant_id=tenant_id)

        logger.info(f"Pipeline starting for tenant: {tenant_id}")

        # ── Stage 0: Ensure schema exists ─────────────────
        logger.info("Initialising Neo4j schema...")
        init_schema(self.neo4j_driver)

        # ── Stage 1: Extract ──────────────────────────────
        # What: pull RawRecords from every connector
        # Why generator: we stream records one at a time rather than
        # loading the entire dataset into memory at once.
        # At real scale (50k+ records) this is critical.
        all_raw_records: list[RawRecord] = []
        workday_manager_map: dict[str, str] = {}  # workday_id → manager_workday_id

        for connector_info in list_connectors():
            connector_id = connector_info["connector_id"]
            creds = ConnectorCredentials(
                connector_id=connector_id,
                tenant_id=tenant_id,
                auth_data={},
            )

            try:
                connector = get_connector(connector_id, creds)

                # Health check before extraction
                health = connector.health_check()
                if not health.is_healthy:
                    msg = f"{connector_id} failed health check: {health.error_message}"
                    logger.warning(msg)
                    result.errors.append(msg)
                    continue

                if not connector.authenticate():
                    msg = f"{connector_id} authentication failed"
                    logger.error(msg)
                    result.errors.append(msg)
                    continue

                # Extract all entity types this connector supports
                schema = connector.discover_schema()
                connector_record_count = 0

                for entity_schema in schema:
                    entity_type = entity_schema.entity_type
                    logger.info(f"Extracting {connector_id}/{entity_type}...")

                    for record in connector.extract_full(entity_type):
                        all_raw_records.append(record)
                        connector_record_count += 1

                        # Capture Workday manager map while extracting
                        # (we need it for the resolver's second pass)
                        if connector_id == "workday" and entity_type == "worker":
                            wid = record.payload.get("workerId")
                            mid = record.payload.get("managerId")
                            if wid and mid:
                                workday_manager_map[wid] = mid

                result.connectors_run.append(connector_id)
                logger.info(f"  → {connector_id}: {connector_record_count} records")

            except Exception as e:
                msg = f"Connector {connector_id} failed: {e}"
                logger.error(msg)
                result.errors.append(msg)

        result.records_extracted = len(all_raw_records)
        logger.info(f"Extraction complete: {result.records_extracted} raw records")

        # ── Stage 2: Normalize ────────────────────────────
        # What: translate each RawRecord to a canonical dict
        # The normalizer returns None for unsupported types — we skip those
        normalized_records = []
        for record in all_raw_records:
            canonical = normalize(record)
            if canonical is not None:
                normalized_records.append(canonical)
            else:
                result.records_skipped += 1

        result.records_normalized = len(normalized_records)
        logger.info(f"Normalization complete: {result.records_normalized} records normalized")

        # ── Stage 3: Resolve ──────────────────────────────
        # What: merge duplicates into canonical entities
        resolver = EntityResolver(tenant_id=tenant_id)
        persons, vendors, accounts, opportunities = resolver.resolve(normalized_records)

        # Second pass: resolve manager canonical_ids
        resolver.resolve_person_managers(persons, workday_manager_map)

        result.persons_resolved = len(persons)
        result.vendors_resolved = len(vendors)
        result.accounts_resolved = len(accounts)
        result.opportunities_resolved = len(opportunities)
        logger.info(
            f"Resolution complete: {len(persons)} persons, "
            f"{len(vendors)} vendors, {len(accounts)} accounts, "
            f"{len(opportunities)} opportunities"
        )

        # ── Stage 4: Write ────────────────────────────────
        # What: upsert everything into Neo4j
        # Wrapped in try/except so a Neo4j outage doesn't abort the whole
        # pipeline — workers can still run on the in-memory resolved data.
        logger.info("Writing to Neo4j...")
        try:
            result.write_stats = self.writer.write_all(persons, vendors, accounts, opportunities)
        except Exception as exc:
            msg = f"Neo4j write failed (graph may be unavailable): {exc}"
            logger.warning(msg)
            result.errors.append(msg)

        result.duration_seconds = time.time() - start
        logger.info(f"Pipeline complete in {result.duration_seconds:.1f}s")

        return result

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        self.neo4j_driver.close()
