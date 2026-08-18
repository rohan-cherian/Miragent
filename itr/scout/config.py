"""
itr/scout/config.py — Centralised configuration for ITR Slice 1.

Shared surface [RS] — both sides have now landed here:
  Rohan:          Gmail OAuth + scopes, MinIO raw lake.
  Sutej (Task 3): DATABASE_URL, TENANT_ID, thresholds, embeddings pins,
                  LLM tiers, ACTION_MODE.

One field, one definition. These are plain class attributes, so a second
assignment of the same name silently wins — if you are adding settings here,
extend the existing block rather than opening a parallel one.

All values come from environment variables (read from itr/.env.local on a
laptop, injected by the platform elsewhere). The code never changes — only
the environment does.
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
    # TENANT_ID / thresholds / ACTION_MODE now live further down — Task 3 landed.

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
    # Task 1: read + send. Space-separated — auth.py urlencodes this as one
    # `scope` parameter. Send scope is required by the Task 21 ActionExecutor.
    gmail_scopes: str = (
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/gmail.send"
    )

    # ── MinIO / S3 raw lake ───────────────────────────────────────────────────
    # Slice 1 raw landing zone. S3-compatible, so the same settings point at
    # real S3 by changing the endpoint and dropping path-style addressing.
    #
    # Credentials are deliberately BLANK here — handover doc section 11 forbids
    # committing them to source. Set them in .env.local (gitignored) or inject
    # them from the platform's secret store. The endpoint is not a credential,
    # so it carries the real default: an Oracle Cloud Compute VM, not local
    # docker. Host:port only, no scheme.
    minio_endpoint: str = "140.245.252.42:9000"
    minio_console_url: str = "http://140.245.252.42:9001"  # web console only
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "raw"
    minio_region: str = "us-east-1"
    minio_secure: bool = False  # True only once this endpoint is behind HTTPS
    minio_addressing_style: str = "path"  # MinIO needs path-style, not virtual-host

    # ── Gmail → raw lake ingestion ────────────────────────────────────────────
    # Ingests EVERY mailbox message into MinIO (no sender filter).
    gmail_raw_prefix: str = "gmail"
    # Path layout. "flat" -> gmail/YYYY/MM/DD/ (single-mailbox POC).
    # "account" -> gmail/<account_id>/YYYY/MM/DD/ (multi-mailbox).
    gmail_raw_path_layout: str = "flat"  # flat | account
    # Which date picks the YYYY/MM/DD folder.
    # "received" -> the message's Gmail internalDate (stable across re-syncs).
    # "ingested" -> wall clock at write time.
    gmail_raw_partition_by: str = "received"  # received | ingested
    # Handover doc sections 3/7/15: the Gmail message ID IS the object name.
    # That makes the key fully derivable, so a HEAD on the path is the
    # duplicate check and no tracking table is needed for correctness.
    gmail_raw_object_pattern: str = "email_{message_id}.json"
    # Attachment bytes are inlined base64. Above this size the attachment is
    # recorded with metadata + sha256 but no bytes (truncated=true).
    gmail_raw_max_attachment_bytes: int = 26_214_400  # 25 MiB
    gmail_raw_include_spam_trash: bool = True
    # Optional Gmail search filter for backfill. Empty = whole mailbox.
    # Task 8 still drops system/bulk mail after fetch.
    gmail_raw_query: str = ""
    gmail_raw_page_size: int = 100
    # Safety cap per run so one invocation cannot spin forever on a huge mailbox.
    gmail_raw_max_per_run: int = 500
    # Re-attempt ledger rows stuck in 'pending' after this many seconds.
    gmail_raw_pending_retry_seconds: int = 300

    # ── Offline fixtures (Task 9) ─────────────────────────────────────────────
    # When true, get_client() returns a FixtureClient reading from
    # gmail_fixtures_dir instead of calling Gmail. The demo, and the whole
    # adapter test suite, then run with no network and no credentials.
    use_gmail_fixtures: bool = False
    gmail_fixtures_dir: str = "scout/gmail/fixtures"

    # ── Gmail push (Cloud Pub/Sub) ────────────────────────────────────────────
    # Optional. The 60s poller is the workhorse; push just triggers it sooner.
    gmail_pubsub_topic: str = ""  # projects/<proj>/topics/<topic>
    gmail_push_shared_secret: str = ""  # ?token= guard on the push endpoint
    gmail_push_label_ids: str = ""  # comma-separated; empty = whole mailbox

    # ── Action mode ───────────────────────────────────────────────────────────
    # MVP Phase 1: recommendation only, nothing is dispatched.
    # Doc's exact spec (Task 3): env("ACTION_MODE", "draft_only")
    # values: "draft_only" | "gated_execute"
    # Resolved at merge: the doc's draft_only/gated_execute wins over the older
    # DRY_RUN/LIVE, which this side had already removed. Task 22
    # (dispatch_write) gates on these two values.
    action_mode: str = "draft_only"  # draft_only | gated_execute

    # ── Connections — Sutej ─────────────────────────────────────────────────────
    # Port 5434, not 5432: infra/docker-compose.yml binds the itr container to
    # 5434 because 5432 is already a native Postgres on this machine. Pointing
    # here at 5432 does not fail — it silently connects to the wrong database.
    # SQLAlchemy dialect form; psycopg3 callers want `database_dsn` below.
    database_url: str = "postgresql+psycopg://postgres:itr@localhost:5434/itr"
    # MinIO settings live in the raw-lake block above — one definition only.
    qdrant_url: str = "http://localhost:6333"

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
    def database_dsn(self) -> str:
        """`database_url` in a form psycopg3 and psql accept.

        SQLAlchemy needs the `postgresql+psycopg://` dialect prefix; psycopg
        rejects it outright (ProgrammingError) and so does psql. Strip the
        driver so one setting serves both, rather than keeping two in sync.
        """
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

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
