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

    # ── MinIO / S3 raw lake ───────────────────────────────────────────────────
    # Slice 1 raw landing zone. S3-compatible, so the same settings point at
    # real S3 by changing the endpoint and dropping path-style addressing.
    #
    # Credentials are deliberately BLANK here — handover doc section 11 forbids
    # committing them to source. Set them in .env.local (gitignored) or inject
    # them from the platform's secret store.
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "raw"
    minio_region: str = "us-east-1"
    minio_secure: bool = False  # informational; scheme comes from the endpoint
    minio_addressing_style: str = "path"  # MinIO needs path-style, not virtual-host

    # ── Gmail → raw lake ingestion ────────────────────────────────────────────
    # Distinct from the customer-filtered ticket sync above: the raw lake takes
    # EVERY message, unfiltered. Downstream layers do the filtering.
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
    # Optional Gmail search filter for backfill. Empty = literally all mail.
    gmail_raw_query: str = ""
    gmail_raw_page_size: int = 100
    # Safety cap per run so one invocation cannot spin forever on a huge mailbox.
    gmail_raw_max_per_run: int = 500
    # Re-attempt ledger rows stuck in 'pending' after this many seconds.
    gmail_raw_pending_retry_seconds: int = 300

    # ── Gmail push (Cloud Pub/Sub) ────────────────────────────────────────────
    # Optional. The 60s poller is the workhorse; push just triggers it sooner.
    gmail_pubsub_topic: str = ""  # projects/<proj>/topics/<topic>
    gmail_push_shared_secret: str = ""  # ?token= guard on the push endpoint
    gmail_push_label_ids: str = ""  # comma-separated; empty = whole mailbox

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
