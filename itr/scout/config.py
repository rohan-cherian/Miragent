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
    tenant_id: str = "dev-tenant"
    tenant_name: str = "Development Tenant"

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
    # Gate on dispatch_write. Slice 1 ships DRY_RUN; LIVE requires an approved
    # decision and is the only path that reaches GmailAdapter.send_reply().
    action_mode: str = "DRY_RUN"  # DRY_RUN | LIVE

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
