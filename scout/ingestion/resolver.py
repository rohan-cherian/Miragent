"""
scout/ingestion/resolver.py — Entity resolution engine.

THE HARDEST PROBLEM IN DATA ENGINEERING.

The problem: the same real-world entity appears multiple times —
once per source system — each with a different ID and possibly
slightly different data.

  Workday:    workerId=WD-0001, name="Sarah Chen", email="s.chen@acmecorp.com"
  Salesforce: Id=005Dn..., Name="Sarah Chen", Email="s.chen@acmecorp.com"

These are TWO records but ONE person.

The resolver:
  1. Groups records that refer to the same entity (MATCHING)
  2. Merges their data into one canonical record (MERGING)
  3. Assigns a stable canonical_id to each unique entity
  4. Tracks which source systems contributed (PROVENANCE)

SPRINT 1 STRATEGY: Email-as-primary-key
  If two records share the same email → they're the same person.
  Email matching is high confidence (>99% precision for business emails).
  Confidence score: 1.0

SPRINT 2 WILL ADD: Fuzzy name + department matching
  For records with no email (some vendor contacts, external users).
  Uses Jaro-Winkler similarity + department as blocking key.
  Confidence score: 0.75-0.92 (goes to human review queue if < 0.75)

MERGING STRATEGY: Source-of-truth hierarchy
  When two records have conflicting values for the same field,
  we apply priority rules:
  People fields:  Workday > Okta > Salesforce > other
  Vendor fields:  NetSuite > contracts system > other
  A field from a lower-priority source only fills in if the
  higher-priority source has None for that field.
"""

import logging
from collections import defaultdict
from typing import Any

from scout.db.weaviate_client import VectorResolverBase, get_vector_resolver
from scout.graph.models import (
    CanonicalAccount,
    CanonicalOpportunity,
    CanonicalPerson,
    CanonicalVendor,
    make_canonical_id,
)

logger = logging.getLogger(__name__)

# Minimum similarity score to merge two vendor records as the same entity.
# 0.88 is high enough to avoid false positives across different categories
# (e.g. "Oracle" vs "Oracle NetSuite" should merge; "Oracle" vs "SAP" should not).
VENDOR_DEDUP_CERTAINTY = 0.88

# Source of truth priority: index 0 = highest priority
PERSON_SOURCE_PRIORITY = [
    "workday", "sap", "adp", "rippling", "ukg", "gusto", "bamboohr",
    "okta", "azure_ad", "google_workspace", "jumpcloud",
    "dynamics_crm", "hubspot", "pipedrive", "zoho",
    "salesforce",
    "zendesk", "freshservice", "jira", "servicenow",
    "slack",
]
VENDOR_SOURCE_PRIORITY = ["netsuite", "coupa", "concur"]


class EntityResolver:
    """
    Resolves normalized records into canonical entities.

    Usage:
        resolver = EntityResolver(tenant_id="acme-corp")
        persons, vendors, accounts = resolver.resolve(normalized_records)
    """

    def __init__(
        self,
        tenant_id: str,
        vector_resolver: VectorResolverBase | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        # Inject vector resolver (or create default via factory).
        # None disables semantic deduplication (used in unit tests that
        # don't need it).
        self._vector: VectorResolverBase | None = (
            vector_resolver if vector_resolver is not None
            else get_vector_resolver()
        )

    def resolve(
        self,
        normalized_records: list[dict[str, Any]],
    ) -> tuple[list[CanonicalPerson], list[CanonicalVendor], list[CanonicalAccount], list[CanonicalOpportunity]]:
        """
        Main entry point. Takes all normalized records and returns
        four lists of canonical entities, ready to write to Neo4j.
        """
        # Split records by entity type
        person_records = [r for r in normalized_records if r.get("entity_type") == "person"]
        vendor_records = [r for r in normalized_records if r.get("entity_type") == "vendor"]
        account_records = [r for r in normalized_records if r.get("entity_type") == "account"]
        opportunity_records = [r for r in normalized_records if r.get("entity_type") == "opportunity"]

        persons = self._resolve_persons(person_records)
        vendors = self._resolve_vendors(vendor_records)
        accounts = self._resolve_accounts(account_records, persons)
        opportunities = self._resolve_opportunities(opportunity_records, persons, accounts)

        # Now that we have canonical persons, resolve manager relationships
        self._resolve_manager_ids(persons)

        logger.info(
            f"Resolution complete: {len(persons)} persons, "
            f"{len(vendors)} vendors, {len(accounts)} accounts, "
            f"{len(opportunities)} opportunities"
        )
        return persons, vendors, accounts, opportunities

    # ─────────────────────────────────────────────────────
    # PERSON RESOLUTION
    # ─────────────────────────────────────────────────────

    def _resolve_persons(self, records: list[dict[str, Any]]) -> list[CanonicalPerson]:
        """
        Resolve person records across all source systems.

        ALGORITHM:
          1. Group all records by email (the primary natural key)
          2. For each email group, merge records using source-of-truth hierarchy
          3. Build one CanonicalPerson per unique email

        EXAMPLE:
          Input:
            {"email": "s.chen@acmecorp.com", "_source_connector": "workday",
             "job_title": "VP of Sales", "department": "Sales", "workday_id": "WD-0001"}
            {"email": "s.chen@acmecorp.com", "_source_connector": "salesforce",
             "job_title": "VP of Sales", "salesforce_id": "005Dn..."}

          Output:
            CanonicalPerson(
              email="s.chen@acmecorp.com",
              job_title="VP of Sales",       ← from Workday (higher priority)
              workday_id="WD-0001",
              salesforce_id="005Dn...",
              source_systems=["workday", "salesforce"],
              confidence_score=1.0
            )
        """
        # Step 1: Group by email
        by_email: dict[str, list[dict]] = defaultdict(list)
        no_email: list[dict] = []

        for record in records:
            email = record.get("email")
            if email:
                by_email[email].append(record)
            else:
                no_email.append(record)
                logger.debug(f"Person record with no email from {record.get('_source_connector')}: {record.get('full_name')}")

        # Step 2: Merge each email group
        canonical_persons: list[CanonicalPerson] = []

        for email, group in by_email.items():
            person = self._merge_person_group(email, group)
            canonical_persons.append(person)

        # Step 3: Records with no email become their own entity
        # (they can't be matched to anything else)
        for record in no_email:
            # Use name as a fallback key if email is missing
            name = record.get("full_name", "unknown")
            source_id = record.get("_source_id", "")
            fake_key = f"noemail:{source_id}:{name}"
            person = self._merge_person_group(None, [record], fallback_key=fake_key)
            canonical_persons.append(person)

        logger.info(
            f"Person resolution: {len(records)} records → "
            f"{len(canonical_persons)} canonical persons "
            f"({len(by_email)} matched by email, {len(no_email)} unmatched)"
        )
        return canonical_persons

    def _merge_person_group(
        self,
        email: str | None,
        group: list[dict[str, Any]],
        fallback_key: str | None = None,
    ) -> CanonicalPerson:
        """
        Merge a group of records (all referring to the same person) into
        one CanonicalPerson using the source-of-truth hierarchy.

        The merge strategy:
          - Sort records by source priority (Workday first, etc.)
          - For each field, use the value from the highest-priority source
            that has a non-None value for that field
        """
        # Sort by source priority — highest priority first
        group_sorted = sorted(
            group,
            key=lambda r: self._source_priority(r.get("_source_connector", ""), PERSON_SOURCE_PRIORITY),
        )

        # Merge: first non-None value from priority-sorted sources wins
        merged: dict[str, Any] = {}
        source_systems: list[str] = []

        for record in group_sorted:
            source = record.get("_source_connector", "unknown")
            if source not in source_systems:
                source_systems.append(source)
            for key, value in record.items():
                if not key.startswith("_") and key != "entity_type":
                    if merged.get(key) is None and value is not None:
                        merged[key] = value

        # Determine confidence score
        # Multiple sources matching = high confidence; single source = still 1.0 for email match
        confidence = 1.0 if len(group) > 1 else 0.95

        # Generate stable canonical_id
        natural_key = email or fallback_key or merged.get("full_name", "unknown")
        canonical_id = make_canonical_id("person", self.tenant_id, natural_key)

        return CanonicalPerson(
            canonical_id=canonical_id,
            tenant_id=self.tenant_id,
            email=email or "",
            full_name=merged.get("full_name", "Unknown"),
            employee_id=merged.get("employee_id"),
            job_title=merged.get("job_title"),
            department=merged.get("department"),
            location=merged.get("location"),
            cost_center=merged.get("cost_center"),
            employment_type=merged.get("employment_type") or "Regular",
            is_active=merged.get("is_active", True),
            start_date=merged.get("start_date"),
            workday_id=merged.get("workday_id"),
            salesforce_id=merged.get("salesforce_id"),
            source_systems=source_systems,
            confidence_score=confidence,
            # manager_canonical_id is resolved in a second pass
            # after all persons have canonical_ids assigned
            manager_canonical_id=None,
            # Store workday manager id temporarily for later resolution
            # We'll use a private attribute trick via extra field
        )

    def _resolve_manager_ids(self, persons: list[CanonicalPerson]) -> None:
        """
        Second pass: resolve manager_workday_id → manager_canonical_id.

        WHY A SECOND PASS?
        When processing Sarah Chen, her manager (the CEO) may not have been
        processed yet. We can't resolve the canonical_id of someone who
        doesn't exist in our persons list yet.

        Solution: first build all persons (pass 1), then resolve managers (pass 2).

        This is the classic "forward reference" problem in graph construction.
        """
        # Build lookup indices for fast resolution
        by_workday_id: dict[str, CanonicalPerson] = {
            p.workday_id: p for p in persons if p.workday_id
        }
        by_salesforce_id: dict[str, CanonicalPerson] = {
            p.salesforce_id: p for p in persons if p.salesforce_id
        }
        by_email: dict[str, CanonicalPerson] = {
            p.email: p for p in persons if p.email
        }

        # We need to re-extract manager_workday_id that was stored during normalization
        # We'll rebuild person records from normalizer output to get this
        # For now we'll use a pragmatic approach: query from the raw workday data
        # This is done in the pipeline which passes manager_map explicitly
        # See _resolve_person_managers_from_map() called by pipeline
        pass

    def resolve_person_managers(
        self,
        persons: list[CanonicalPerson],
        workday_manager_map: dict[str, str],
    ) -> None:
        """
        Resolve manager relationships using the Workday manager map.

        workday_manager_map: {workday_id → manager_workday_id}

        Called by the pipeline after resolve() returns persons.
        """
        by_workday_id: dict[str, CanonicalPerson] = {
            p.workday_id: p for p in persons if p.workday_id
        }

        resolved = 0
        for person in persons:
            if not person.workday_id:
                continue
            manager_wid = workday_manager_map.get(person.workday_id)
            if manager_wid and manager_wid in by_workday_id:
                manager = by_workday_id[manager_wid]
                person.manager_canonical_id = manager.canonical_id
                resolved += 1

        logger.info(f"Resolved {resolved} manager relationships")

    # ─────────────────────────────────────────────────────
    # VENDOR RESOLUTION
    # ─────────────────────────────────────────────────────

    def _resolve_vendors(self, records: list[dict[str, Any]]) -> list[CanonicalVendor]:
        """
        Resolve vendor records with Weaviate-powered semantic deduplication.

        Sprint 20 upgrade: vendor names are indexed into the vector store as
        they're processed. Before creating a new CanonicalVendor, we query
        Weaviate for semantically similar names. If a match above the
        VENDOR_DEDUP_CERTAINTY threshold is found, the two records are merged
        rather than creating a separate vendor node.

        This catches cases that exact/fuzzy matching misses:
          "Salesforce Inc."  + "SFDC"          → one Salesforce vendor
          "Microsoft Azure"  + "Azure AD"       → one Microsoft vendor
          "SAP S/4HANA"     + "SAP ERP"        → one SAP vendor
        """
        # canonical_id → CanonicalVendor (built so far this run)
        built: dict[str, CanonicalVendor] = {}

        for record in records:
            name = record.get("name", "")
            if not name:
                continue

            # ── Semantic dedup via Weaviate ────────────────────────────────
            matched_canonical_id: str | None = None
            if self._vector is not None:
                try:
                    similar = self._vector.find_similar(
                        entity_type="vendor",
                        name=name,
                        tenant_id=self.tenant_id,
                        limit=3,
                        min_certainty=VENDOR_DEDUP_CERTAINTY,
                    )
                    if similar:
                        matched_canonical_id = similar[0].canonical_id
                        logger.debug(
                            f"Vendor semantic match: '{name}' → '{similar[0].name}' "
                            f"(certainty={similar[0].certainty})"
                        )
                except Exception as exc:
                    logger.warning(f"Weaviate vendor lookup failed for '{name}': {exc}")

            if matched_canonical_id and matched_canonical_id in built:
                # ── Merge into existing vendor ─────────────────────────────
                existing = built[matched_canonical_id]
                source = record.get("_source_connector", "unknown")
                if source not in existing.source_systems:
                    existing.source_systems.append(source)
                # Take higher spend (more complete record wins)
                incoming_spend = record.get("annual_spend") or 0.0
                if incoming_spend > existing.annual_spend:
                    existing.annual_spend = incoming_spend
                # Fill in missing fields from this record
                for field in ("category", "email", "phone", "payment_terms",
                              "contract_renewal", "primary_contact"):
                    if getattr(existing, field, None) is None and record.get(field):
                        setattr(existing, field, record[field])
                logger.info(
                    f"Vendor dedup: merged '{name}' into existing "
                    f"'{existing.name}' (canonical={matched_canonical_id})"
                )
                continue

            # ── Create new canonical vendor ────────────────────────────────
            canonical_id = make_canonical_id("vendor", self.tenant_id, name)
            vendor = CanonicalVendor(
                canonical_id=canonical_id,
                tenant_id=self.tenant_id,
                name=name,
                normalized_name=record.get("normalized_name", name.lower()),
                category=record.get("category"),
                email=record.get("email"),
                phone=record.get("phone"),
                is_active=record.get("is_active", True),
                annual_spend=record.get("annual_spend") or 0.0,
                payment_terms=record.get("payment_terms"),
                contract_renewal=record.get("contract_renewal"),
                primary_contact=record.get("primary_contact"),
                netsuite_id=record.get("netsuite_id"),
                source_systems=[record.get("_source_connector", "netsuite")],
            )
            built[canonical_id] = vendor

            # Index into Weaviate for future dedup within this run
            if self._vector is not None:
                try:
                    self._vector.index_entity(
                        entity_type="vendor",
                        canonical_id=canonical_id,
                        name=name,
                        tenant_id=self.tenant_id,
                        extra={"category": vendor.category or ""},
                    )
                except Exception as exc:
                    logger.warning(f"Weaviate index failed for vendor '{name}': {exc}")

        vendors = list(built.values())
        logger.info(
            f"Vendor resolution: {len(records)} records → "
            f"{len(vendors)} canonical vendors "
            f"({len(records) - len(vendors)} merged by semantic dedup)"
        )
        return vendors

    # ─────────────────────────────────────────────────────
    # ACCOUNT RESOLUTION
    # ─────────────────────────────────────────────────────

    def _resolve_accounts(
        self,
        records: list[dict[str, Any]],
        persons: list[CanonicalPerson],
    ) -> list[CanonicalAccount]:
        """
        Resolve account records and link to owner canonical_ids.

        The owner_salesforce_id in the normalized record is a Salesforce user ID.
        We need to find the CanonicalPerson with that salesforce_id and use
        their canonical_id instead. This is what makes the OWNS edge possible.
        """
        by_sfdc_id: dict[str, CanonicalPerson] = {
            p.salesforce_id: p for p in persons if p.salesforce_id
        }

        accounts: list[CanonicalAccount] = []
        for record in records:
            name = record.get("name", "")
            if not name:
                continue

            # Resolve owner
            owner_sfdc_id = record.get("owner_salesforce_id")
            owner_canonical_id = None
            if owner_sfdc_id and owner_sfdc_id in by_sfdc_id:
                owner_canonical_id = by_sfdc_id[owner_sfdc_id].canonical_id

            canonical_id = make_canonical_id("account", self.tenant_id, name)
            account = CanonicalAccount(
                canonical_id=canonical_id,
                tenant_id=self.tenant_id,
                name=name,
                industry=record.get("industry"),
                account_type=record.get("account_type"),
                annual_revenue=record.get("annual_revenue"),
                employee_count=record.get("employee_count"),
                owner_canonical_id=owner_canonical_id,
                salesforce_id=record.get("_source_id"),
                source_systems=[record.get("_source_connector", "salesforce")],
            )
            accounts.append(account)

        return accounts

    def _resolve_opportunities(
        self,
        records: list[dict[str, Any]],
        persons: list[CanonicalPerson],
        accounts: list[CanonicalAccount],
    ) -> list[CanonicalOpportunity]:
        """
        Resolve opportunity records and link to canonical Person (AE) and Account.

        Each opportunity is unique by name — no cross-system deduplication
        needed in Sprint 4 (opportunities live only in CRM systems).
        """
        from datetime import datetime

        by_sfdc_person: dict[str, CanonicalPerson] = {
            p.salesforce_id: p for p in persons if p.salesforce_id
        }
        by_sfdc_account: dict[str, CanonicalAccount] = {
            a.salesforce_id: a for a in accounts if a.salesforce_id
        }

        opportunities: list[CanonicalOpportunity] = []
        for record in records:
            name = record.get("name", "")
            if not name:
                continue

            # Compute days in pipeline from created date in source
            created_raw = record.get("created_date") or record.get("_ingested_at")
            days_in_pipeline = 0
            if created_raw:
                try:
                    created_dt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                    delta = datetime.utcnow() - created_dt.replace(tzinfo=None)
                    days_in_pipeline = max(0, delta.days)
                except Exception:
                    days_in_pipeline = 0

            # Resolve owner
            owner_sfdc_id = record.get("owner_salesforce_id")
            owner_canonical_id = None
            if owner_sfdc_id and owner_sfdc_id in by_sfdc_person:
                owner_canonical_id = by_sfdc_person[owner_sfdc_id].canonical_id

            # Resolve account
            account_sfdc_id = record.get("account_salesforce_id")
            account_canonical_id = None
            if account_sfdc_id and account_sfdc_id in by_sfdc_account:
                account_canonical_id = by_sfdc_account[account_sfdc_id].canonical_id

            canonical_id = make_canonical_id("opp", self.tenant_id, name)
            opp = CanonicalOpportunity(
                canonical_id=canonical_id,
                tenant_id=self.tenant_id,
                name=name,
                stage=record.get("stage"),
                amount=record.get("amount") or 0.0,
                close_date=record.get("close_date"),
                probability=record.get("probability") or 0,
                is_closed=record.get("is_closed", False),
                is_won=record.get("is_won", False),
                account_canonical_id=account_canonical_id,
                owner_canonical_id=owner_canonical_id,
                days_in_pipeline=days_in_pipeline,
                salesforce_id=record.get("salesforce_id") or record.get("_source_id"),
                source_systems=[record.get("_source_connector", "salesforce")],
            )
            opportunities.append(opp)

        return opportunities

    # ─────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────

    @staticmethod
    def _source_priority(connector_id: str, priority_list: list[str]) -> int:
        """
        Return the priority index for a connector.
        Lower index = higher priority.
        Unknown connectors go to the end (lowest priority).
        """
        try:
            return priority_list.index(connector_id)
        except ValueError:
            return len(priority_list)
