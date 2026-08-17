-- src_gmail raw-lake bookkeeping — Gmail → MinIO raw bucket
-- Apply: poetry run python scripts/load_gmail_schema.py
--
-- NOT the duplicate guard. Per handover doc section 8 the bucket itself is the
-- authority: the object key is fully derived from the Gmail message ID, so a
-- HEAD on that exact path before the PUT is the duplicate check. This table is
-- an audit trail plus the incremental cursor, which the bucket cannot hold.
--
-- Losing this table costs a slower re-scan, never a duplicate object.

CREATE SCHEMA IF NOT EXISTS src_gmail;

CREATE TABLE IF NOT EXISTS src_gmail.raw_objects (
    id                BIGSERIAL PRIMARY KEY,
    account_id        TEXT NOT NULL,
    gmail_message_id  TEXT NOT NULL,
    gmail_thread_id   TEXT,
    object_key        TEXT NOT NULL,
    partition_date    DATE NOT NULL,
    content_sha256    TEXT,
    size_bytes        BIGINT,
    internal_date_ms  BIGINT,
    attachment_count  INTEGER NOT NULL DEFAULT 0,
    written_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_raw_objects_account_message UNIQUE (account_id, gmail_message_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_objects_partition
    ON src_gmail.raw_objects (account_id, partition_date);

CREATE INDEX IF NOT EXISTS idx_raw_objects_key
    ON src_gmail.raw_objects (object_key);

-- Messages deliberately not stored, so a permanent problem is visible rather
-- than silently retried forever (handover doc section 16).
CREATE TABLE IF NOT EXISTS src_gmail.raw_skipped (
    id                BIGSERIAL PRIMARY KEY,
    account_id        TEXT NOT NULL,
    gmail_message_id  TEXT,
    reason            TEXT NOT NULL,
    detail            TEXT,
    seen_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_skipped_account
    ON src_gmail.raw_skipped (account_id, seen_at DESC);

-- history_id cursor for the raw pipeline.
-- Named sync_state because that is what the Slice-1 doc calls it (Task 5:
-- "src_gmail.sync_state stays EXACTLY as built"; Task 6 checkpoints
-- sync_state.history_id). Databases created before that naming carry it as
-- raw_sync_state; 003 migrates them. The shape below is the one the doc means
-- by "as built" — it is unchanged, only the name moved.
CREATE TABLE IF NOT EXISTS src_gmail.sync_state (
    account_id          TEXT PRIMARY KEY,
    history_id          TEXT,
    backfill_done       BOOLEAN NOT NULL DEFAULT FALSE,
    backfill_page_token TEXT,
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    watch_expiration_ms BIGINT
);
