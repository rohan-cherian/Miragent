"""
scout/db/weaviate_client.py — Weaviate vector/semantic resolution client.

Weaviate is a vector database. Scout uses it for one hard problem:
semantic entity deduplication.

THE PROBLEM:
  The same real-world vendor appears across systems with different names:
    NetSuite:   "Salesforce Inc."
    Coupa:      "salesforce.com"
    Concur:     "SFDC"
    Bill.com:   "Salesforce CRM"

  Exact and fuzzy string matching (Levenshtein/Jaro-Winkler) fail on these
  because "Salesforce Inc." and "SFDC" are character-level very different,
  but semantically identical. Vector embeddings solve this.

THE SOLUTION:
  When a vendor is indexed, we embed its name + category into a dense vector.
  At resolution time, candidate names are embedded the same way and we query
  Weaviate for the most similar existing entry above a certainty threshold.

DESIGN PATTERN — Three-layer abstraction:

  VectorResolverBase    ← abstract interface
  MockVectorResolver    ← trigram + alias dict, no Docker needed
  RealWeaviateResolver  ← weaviate-client with text2vec-contextionary

SCHEMA (Weaviate class: VendorEntity):
  name         text    — vendor name as it appears in source system
  category     text    — "CRM", "HRIS", "ERP", etc.
  canonical_id text    — Scout canonical ID (returned on match)
  tenant_id    text    — tenant partition field

SCHEMA (Weaviate class: PersonEntity):
  full_name    text    — person's full name
  job_title    text    — "Senior Software Engineer", "VP of Sales"
  department   text    — "Engineering", "Sales", etc.
  canonical_id text
  tenant_id    text
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from scout.config import settings

logger = logging.getLogger(__name__)

# ── Known alias map (seed for MockVectorResolver) ─────────────────────────────
# Maps alternative names / abbreviations → canonical name fragment.
# Used so the mock can identify "SFDC" → "Salesforce" without embeddings.

VENDOR_ALIASES: dict[str, str] = {
    # CRM
    "sfdc": "salesforce",
    "salesforce inc": "salesforce",
    "salesforce inc.": "salesforce",
    "salesforce.com": "salesforce",
    "salesforce crm": "salesforce",
    "hubspot crm": "hubspot",
    "ms dynamics": "microsoft dynamics",
    "dynamics 365": "microsoft dynamics",
    "dynamics crm": "microsoft dynamics",
    # HRIS
    "adp workforce": "adp",
    "adp run": "adp",
    "bamboo": "bamboohr",
    "bamboo hr": "bamboohr",
    "workday hcm": "workday",
    # Finance / ERP
    "netsuite erp": "netsuite",
    "oracle netsuite": "netsuite",
    "quickbooks online": "quickbooks",
    "intuit quickbooks": "quickbooks",
    "sap s4hana": "sap",
    "sap erp": "sap",
    "sage": "sage intacct",
    # Identity
    "aad": "azure ad",
    "azure active directory": "azure ad",
    "microsoft azure ad": "azure ad",
    "google workspace": "google workspace",
    "g suite": "google workspace",
    "gsuite": "google workspace",
    # Expense
    "sap concur": "concur",
    "brex card": "brex",
    "ramp card": "ramp",
    # Helpdesk
    "servicenow itsm": "servicenow",
    "zendesk support": "zendesk",
    "fresh service": "freshservice",
    # Dev tools
    "atlassian jira": "jira",
    "github enterprise": "github",
    "slack enterprise": "slack",
    "msft teams": "microsoft teams",
    "ms teams": "microsoft teams",
}

# ── Data model ────────────────────────────────────────────────────────────────


class SimilarEntity:
    """A candidate match returned by vector search."""

    def __init__(
        self,
        canonical_id: str,
        name: str,
        certainty: float,
        entity_type: str,
    ) -> None:
        self.canonical_id = canonical_id
        self.name = name
        self.certainty = certainty    # 0.0–1.0; 1.0 = identical
        self.entity_type = entity_type


# ── Abstract base ─────────────────────────────────────────────────────────────


class VectorResolverBase(ABC):
    """Abstract interface for the vector-based entity resolver."""

    @abstractmethod
    def index_entity(
        self,
        entity_type: str,
        canonical_id: str,
        name: str,
        tenant_id: str,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """
        Index an entity's text into the vector store.
        Returns the Weaviate/internal object UUID for the indexed entry.
        """

    @abstractmethod
    def find_similar(
        self,
        entity_type: str,
        name: str,
        tenant_id: str,
        limit: int = 5,
        min_certainty: float = 0.85,
    ) -> list[SimilarEntity]:
        """
        Return entities whose vector embedding is within min_certainty
        of the query name. Results are sorted by certainty descending.
        """

    @abstractmethod
    def entity_count(self, entity_type: str, tenant_id: str) -> int:
        """Return count of indexed entities."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the Weaviate cluster is reachable."""

    def close(self) -> None:
        """Release any connection resources."""


# ── Mock implementation ───────────────────────────────────────────────────────


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _trigrams(s: str) -> set[str]:
    """Character 3-grams of a normalized string."""
    s = f"  {s}  "
    return {s[i : i + 3] for i in range(len(s) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    """Dice coefficient on character trigrams — fast approximate similarity."""
    ta = _trigrams(_normalize(a))
    tb = _trigrams(_normalize(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    return 2 * intersection / (len(ta) + len(tb))


class MockVectorResolver(VectorResolverBase):
    """
    In-memory vector resolver using trigram similarity + alias dictionary.

    No Weaviate service needed. Deterministic results — useful in tests
    and on developer laptops.

    Similarity is computed as:
      max(trigram_similarity, alias_match)

    where alias_match is 1.0 if the normalized name maps to a known alias.
    """

    def __init__(self) -> None:
        # Store indexed entities: entity_type → list of (canonical_id, name, tenant_id)
        self._store: dict[str, list[tuple[str, str, str]]] = {}
        self._counter = 0

    def index_entity(
        self,
        entity_type: str,
        canonical_id: str,
        name: str,
        tenant_id: str,
        extra: dict[str, Any] | None = None,
    ) -> str:
        bucket = self._store.setdefault(entity_type, [])
        # Avoid duplicate indexing of same canonical_id
        if not any(c == canonical_id and t == tenant_id for c, _, t in bucket):
            bucket.append((canonical_id, name, tenant_id))
        self._counter += 1
        return f"mock-uuid-{self._counter}"

    def find_similar(
        self,
        entity_type: str,
        name: str,
        tenant_id: str,
        limit: int = 5,
        min_certainty: float = 0.85,
    ) -> list[SimilarEntity]:
        bucket = self._store.get(entity_type, [])
        if not bucket:
            return []

        norm_query = _normalize(name)
        # Check alias table with both normalized and raw-lowercase forms
        # (raw preserves dots/hyphens that normalization removes)
        alias_key = VENDOR_ALIASES.get(norm_query) or VENDOR_ALIASES.get(name.lower().strip())

        results: list[SimilarEntity] = []
        for canonical_id, indexed_name, tid in bucket:
            if tid != tenant_id:
                continue
            norm_indexed = _normalize(indexed_name)

            # Check alias table first
            if alias_key and (
                norm_indexed == alias_key
                or alias_key in norm_indexed
                or norm_indexed in alias_key
            ):
                certainty = 0.95
            else:
                certainty = _trigram_similarity(norm_query, norm_indexed)

            if certainty >= min_certainty:
                results.append(SimilarEntity(
                    canonical_id=canonical_id,
                    name=indexed_name,
                    certainty=round(certainty, 3),
                    entity_type=entity_type,
                ))

        results.sort(key=lambda r: r.certainty, reverse=True)
        return results[:limit]

    def entity_count(self, entity_type: str, tenant_id: str) -> int:
        return sum(
            1 for _, _, tid in self._store.get(entity_type, [])
            if tid == tenant_id
        )

    def health_check(self) -> bool:
        return True


# ── Real implementation ───────────────────────────────────────────────────────


class RealWeaviateResolver(VectorResolverBase):
    """
    Production resolver using the Weaviate vector database.

    Uses text2vec-contextionary for embedding (no OpenAI key required).
    Creates schema classes on first connect if they don't exist.

    Weaviate's certainty score (0–1) maps to cosine similarity of the
    embedding vectors — 1.0 is identical, 0.85+ is a strong match.
    """

    VENDOR_CLASS = "VendorEntity"
    PERSON_CLASS = "PersonEntity"

    def __init__(self) -> None:
        try:
            import weaviate  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "weaviate-client not installed. "
                "Run: poetry add weaviate-client"
            ) from exc

        self._client = weaviate.Client(
            url=settings.weaviate_url,
            timeout_config=(5, 30),
        )
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create Weaviate class schemas if they don't exist."""
        for class_def in [self._vendor_schema(), self._person_schema()]:
            class_name = class_def["class"]
            if not self._client.schema.exists(class_name):
                self._client.schema.create_class(class_def)
                logger.info(f"Created Weaviate class: {class_name}")

    @staticmethod
    def _vendor_schema() -> dict:
        return {
            "class": RealWeaviateResolver.VENDOR_CLASS,
            "description": "Vendor/supplier entity for semantic deduplication",
            "vectorizer": "text2vec-contextionary",
            "moduleConfig": {
                "text2vec-contextionary": {"vectorizeClassName": False}
            },
            "properties": [
                {"name": "name", "dataType": ["text"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": False}}},
                {"name": "category", "dataType": ["text"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": False}}},
                {"name": "canonicalId", "dataType": ["string"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": True}}},
                {"name": "tenantId", "dataType": ["string"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": True}}},
            ],
        }

    @staticmethod
    def _person_schema() -> dict:
        return {
            "class": RealWeaviateResolver.PERSON_CLASS,
            "description": "Person entity for semantic deduplication",
            "vectorizer": "text2vec-contextionary",
            "moduleConfig": {
                "text2vec-contextionary": {"vectorizeClassName": False}
            },
            "properties": [
                {"name": "fullName", "dataType": ["text"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": False}}},
                {"name": "jobTitle", "dataType": ["text"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": False}}},
                {"name": "department", "dataType": ["text"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": False}}},
                {"name": "canonicalId", "dataType": ["string"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": True}}},
                {"name": "tenantId", "dataType": ["string"],
                 "moduleConfig": {"text2vec-contextionary": {"skip": True}}},
            ],
        }

    def _class_for(self, entity_type: str) -> str:
        return self.VENDOR_CLASS if entity_type == "vendor" else self.PERSON_CLASS

    def index_entity(
        self,
        entity_type: str,
        canonical_id: str,
        name: str,
        tenant_id: str,
        extra: dict[str, Any] | None = None,
    ) -> str:
        class_name = self._class_for(entity_type)
        props: dict[str, Any] = {
            "canonicalId": canonical_id,
            "tenantId": tenant_id,
        }
        if entity_type == "vendor":
            props["name"] = name
            props["category"] = (extra or {}).get("category", "")
        else:
            props["fullName"] = name
            props["jobTitle"] = (extra or {}).get("job_title", "")
            props["department"] = (extra or {}).get("department", "")

        uuid = self._client.data_object.create(props, class_name)
        return uuid

    def find_similar(
        self,
        entity_type: str,
        name: str,
        tenant_id: str,
        limit: int = 5,
        min_certainty: float = 0.85,
    ) -> list[SimilarEntity]:
        class_name = self._class_for(entity_type)
        prop = "name" if entity_type == "vendor" else "fullName"

        result = (
            self._client.query
            .get(class_name, ["canonicalId", prop, "tenantId"])
            .with_near_text({"concepts": [name], "certainty": min_certainty})
            .with_where({
                "path": ["tenantId"],
                "operator": "Equal",
                "valueString": tenant_id,
            })
            .with_limit(limit)
            .with_additional(["certainty"])
            .do()
        )

        hits = result.get("data", {}).get("Get", {}).get(class_name, [])
        entities: list[SimilarEntity] = []
        for hit in hits:
            certainty = hit.get("_additional", {}).get("certainty", 0.0)
            entities.append(SimilarEntity(
                canonical_id=hit.get("canonicalId", ""),
                name=hit.get(prop, ""),
                certainty=round(float(certainty), 3),
                entity_type=entity_type,
            ))
        return entities

    def entity_count(self, entity_type: str, tenant_id: str) -> int:
        class_name = self._class_for(entity_type)
        result = (
            self._client.query
            .aggregate(class_name)
            .with_where({
                "path": ["tenantId"],
                "operator": "Equal",
                "valueString": tenant_id,
            })
            .with_meta_count()
            .do()
        )
        count = (
            result.get("data", {})
            .get("Aggregate", {})
            .get(class_name, [{}])[0]
            .get("meta", {})
            .get("count", 0)
        )
        return int(count)

    def health_check(self) -> bool:
        try:
            return self._client.is_ready()
        except Exception:
            return False

    def close(self) -> None:
        try:
            self._client._connection.close()  # type: ignore[attr-defined]
        except Exception:
            pass


# ── Factory ───────────────────────────────────────────────────────────────────


def get_vector_resolver() -> VectorResolverBase:
    """
    Return the appropriate vector resolver based on configuration.

    When USE_MOCK_CONNECTORS=true → MockVectorResolver (trigram + alias dict).
    When USE_MOCK_CONNECTORS=false → RealWeaviateResolver (vector embeddings).
    """
    if settings.use_mock_connectors:
        logger.debug("Using MockVectorResolver (USE_MOCK_CONNECTORS=true)")
        return MockVectorResolver()

    logger.info(f"Connecting to Weaviate at {settings.weaviate_url}")
    return RealWeaviateResolver()
