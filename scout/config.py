"""
scout/config.py — Centralised configuration for Scout.

All values come from environment variables.
On your laptop: read from .env.local
On AWS: injected by ECS from Secrets Manager
On client VPC: injected by Kubernetes from HashiCorp Vault

The code never changes — only the environment does.
This is the 12-Factor App principle in action.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Every config value Scout needs, in one place.

    Pydantic validates types automatically:
    - If NEO4J_URI is missing, startup fails with a clear error
    - If USE_MOCK_CONNECTORS is "true" (string), it becomes True (bool)
    - No silent failures from misconfiguration
    """

    model_config = SettingsConfigDict(
        env_file=".env.local",        # read from this file if it exists
        env_file_encoding="utf-8",
        case_sensitive=False,         # NEO4J_URI and neo4j_uri both work
        extra="ignore",               # ignore unknown env vars (don't crash)
        env_ignore_empty=True,        # empty shell vars don't override .env.local
    )

    # ── Environment ───────────────────────────────────────
    environment: str = "development"
    use_mock_connectors: bool = True  # True on laptop, False in production

    # ── Tenant (the company being scanned) ───────────────
    tenant_id: str = "dev-tenant"
    tenant_name: str = "Development Tenant"

    # ── Neo4j ─────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "miragent_dev"

    # ── ClickHouse ────────────────────────────────────────
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 9000
    clickhouse_user: str = "default"
    clickhouse_password: str = "miragent_dev"
    clickhouse_database: str = "scout"

    # ── Weaviate ──────────────────────────────────────────
    weaviate_url: str = "http://localhost:8080"

    # ── Redis ─────────────────────────────────────────────
    redis_url: str = "redis://:miragent_dev@localhost:6379/0"

    # ── Security (Sprint 13) ──────────────────────────────
    scout_api_key: str = "dev-insecure-key-replace-in-production"
    rate_limit_per_minute: int = 60          # requests per tenant per minute
    rate_limit_enabled: bool = True
    auth_enabled: bool = True                # set False in tests via env
    audit_log_file: str = "logs/audit.log"   # path for SOC 2 audit trail

    # ── SQLite / Auth (Sprint 15) ─────────────────────────
    database_url: str = "sqlite:///./miragent.db"
    jwt_secret: str = "dev-jwt-secret-replace-in-production"
    jwt_algorithm: str = "HS256"

    # ── SSO / OIDC (Sprint 58) ────────────────────────────
    # Base URL for the API — used to build the SSO callback URL.
    # Override in production: API_BASE_URL=https://api.miragent.io
    api_base_url: str = "http://localhost:8000"

    # ── LLM provider ──────────────────────────────────────
    # Which provider powers the AI narrative (GET /insights).
    # Supported values: "anthropic" | "openai" | "gemini" | "ollama"
    # Default: "anthropic" (existing behaviour, requires ANTHROPIC_API_KEY)
    llm_provider: str = "anthropic"

    # Model identifier — interpreted by the selected provider.
    # Examples:
    #   anthropic → "claude-sonnet-4-5"
    #   openai    → "gpt-4o"
    #   gemini    → "gemini-2.0-flash"
    #   ollama    → "llama3.1" (or any model pulled via `ollama pull`)
    llm_model: str = "claude-sonnet-4-5"

    # Optional base URL override.
    # Primarily for Ollama (default: http://localhost:11434) or
    # any OpenAI-compatible custom endpoint (e.g. vLLM, LM Studio).
    # Leave empty to use each provider's default endpoint.
    llm_base_url: str = ""

    # ── Provider API keys ─────────────────────────────────
    # At least one must be set for live LLM calls.
    # If none match the active provider, the system falls back to
    # the template narrative so the insights endpoint never breaks.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # Ollama is local — no API key required.

    # ── Email digest (Sprint 81) ──────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "digest@miragent.io"
    digest_enabled: bool = False   # must be explicitly enabled in production

    # ── Salesforce connector (Sprint 83) ──────────────────────────────────────
    # Connected App credentials — create once in Setup → App Manager.
    # These are the app-level credentials (same for all tenants).
    # Per-tenant refresh tokens are stored in ConnectorCredentialStore (SQLite).
    sf_client_id: str = ""        # Consumer Key from Connected App
    sf_client_secret: str = ""    # Consumer Secret from Connected App
    sf_instance_url: str = "https://login.salesforce.com"  # or sandbox: test.salesforce.com

    # ── Convenience properties ────────────────────────────
    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


# ─────────────────────────────────────────────────────────
# Module-level singleton — import this everywhere
#
# Usage:
#   from scout.config import settings
#   print(settings.neo4j_uri)
# ─────────────────────────────────────────────────────────
settings = Settings()
