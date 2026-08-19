"""
itr/scout/config.py — Centralised configuration for ITR Slice 1.

Shared surface [RS]: Gmail credentials, thresholds, pins, ACTION_MODE.

All values come from environment variables (read from itr/.env.local on a
laptop, injected by the platform elsewhere). The code never changes — only
the environment does.

Carried over from the pre-itr scout/config.py: only the Gmail block moved.
Neo4j / ClickHouse / Weaviate / Redis settings deliberately did NOT come
across — Slice 1 infra is postgres · minio · qdrant only.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every config value ITR Slice 1 needs, in one place."""

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
    )

    # ── Environment ───────────────────────────────────────────────────────────
    environment: str = "development"

    # ── Gmail integration (Desktop OAuth + polling sync) ─────────────────────
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_user: str = "me"
    gmail_redirect_uri: str = "http://127.0.0.1:8089/"
    gmail_refresh_token: str = ""
    gmail_token_path: str = "secrets/gmail_token.json"
    gmail_database_url: str = (
        "postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
    )
    gmail_scopes: str = "https://www.googleapis.com/auth/gmail.readonly"
    # Comma-separated From addresses allowed to become tickets (customer-only sync)
    gmail_customer_senders: str = (
        "motiveminds.vihaan@gmail.com,"
        "motiveminds.jennifer@gmail.com,"
        "motiveminds.ojasvi@gmail.com"
    )

    # ── Action mode ───────────────────────────────────────────────────────────
    # MVP Phase 1: recommendation only, nothing is dispatched.
    # Doc's exact spec (Task 3): env("ACTION_MODE", "draft_only")
    # values: "draft_only" | "gated_execute"
    # CONFLICT: Rohan's earlier code used "DRY_RUN"/"LIVE" — confirm with
    # him which convention wins before Task 22 (dispatch_write) is built.
    action_mode: str = "draft_only"  # draft_only | gated_execute

    # ── Connections — Sutej ─────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://postgres:itr@localhost:5432/itr"
    # MinIO — hosted on Oracle Cloud Compute VM (not local docker).
    # Host:port only, no http:// — client picks http/https via minio_secure.
    minio_endpoint: str = "140.245.252.42:9000"
    minio_console_url: str = "http://140.245.252.42:9001"  # web console only
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False  # True only once this endpoint is behind HTTPS
    minio_bucket_raw: str = "raw"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_name: str = "itr360_chunks"  # Task 17 (index) — Qdrant collection for embedded chunks

    # ── Tenancy ──────────────────────────────────────────────────────────────
    # Doc: "fixed uuid for Northwind Traders" — placeholder until the real
    # UUID is issued/confirmed with the team.
    tenant_id: str = "00000000-0000-0000-0000-000000000001"  # TODO: confirm real Northwind Traders UUID
    tenant_name: str = "Northwind Traders"

    # ── Personas — used by seed_personas.py ────────────────────────────────────
    persona_1_email: str = ""
    persona_2_email: str = ""
    persona_3_email: str = ""

    # ── Thresholds — never hardcode these elsewhere in the codebase ───────────
    # Sign off with the team before Task 17 (embeddings are the one value
    # here that forces a full re-embed if changed later).
    identity_apply: float = 0.90
    identity_probable: float = 0.70
    triage_escalate: float = 0.75
    triage_floor: float = 0.60
    reco_high: float = 0.85
    reco_medium: float = 0.60
    retrieval_floor: float = 0.55
    token_budget: int = 6000
    reopen_window_days: int = 7
    dup_window_hours: int = 24

    # ── Embeddings — OpenAI DIRECT (OpenRouter has no /embeddings endpoint) ────
    embed_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""  # read as EMBED_API_KEY in doc; kept as openai_api_key for clarity
    embed_model: str = "text-embedding-3-large"  # PINNED
    embed_dims: int = 1024  # PINNED — see docs/corpus_datasheet.md, re-embed cost if changed
    embed_batch: int = 128

    # ── Reasoning — OpenRouter for everything ──────────────────────────────────
    llm_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    llm_title: str = "ITR Scout"  # used in X-Title header
    # Model slugs per tier — confirm against current OpenRouter docs before use.
    llm_tiers: dict[str, str] = {
        "fast": "openai/gpt-4o-mini",
        "standard": "anthropic/claude-sonnet-4.5",
        "deep": "anthropic/claude-opus-4.5",
    }
    # Which tier each agent uses.
    agent_tier: dict[str, str] = {
        "triage": "fast",
        "enricher": "fast",
        "dedup": "fast",
        "prioritise": "fast",
        "resolve": "standard",
        "escalate": "standard",
        "curator": "standard",
        "miner": "deep",
    }
    llm_cost_ceiling_usd_per_run: float = 5.00  # hard stop, not a warning

    # ── Neo4j / Redis — added ahead of Slice 3 schedule (Sutej's call) ────────
    # Doc's Slice 1 spec says these aren't needed yet. Nothing in the
    # Slice 1 codebase should import/use these until Slice 3 actually
    # designs the graph + working-memory layers — these are just here
    # so the containers and settings exist in advance.
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "itr_dev"
    redis_url: str = "redis://:itr_dev@localhost:6379/0"

    # ── Convenience properties ────────────────────────────────────────────────
    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


# ─────────────────────────────────────────────────────────
# Module-level singleton — import this everywhere
#
#   from scout.config import settings
# ─────────────────────────────────────────────────────────
settings = Settings()
