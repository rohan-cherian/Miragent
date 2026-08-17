-- itr/schema/003_src_gmail_regrain.sql
-- Slice-1 Task 5 — re-grain src_gmail · ROHAN
-- Apply: poetry run python scripts/load_gmail_schema.py
--
-- A Gmail message is not a ticket. The old 1-message-to-1-ticket mapping turned
-- a five-message thread into five tickets, which makes case correlation
-- impossible. src_gmail becomes a faithful replica of Gmail's own shape;
-- "case" is a canonical concept built later at Task 15.
--
-- Every table carries the seven provenance columns from Task 4's mixin:
--   tenant_id · source_system · external_id · is_synthetic
--   connector_run_id · observed_at · valid_from
--
-- connector_run_id is NOT NULL but has no FK: raw_ingest.runs is created in
-- Task 6, and Task 5 must be applyable on its own. The FK can be added once
-- 004_raw_ingest.sql has run.

-- ── Prerequisites the doc's DDL assumes ──────────────────────────────────────
-- infra/init-schemas.sql creates raw_ingest/staging/itr360/agent_ops/audit but
-- not src_gmail, and installs the vector extension but not citext. The DDL
-- below needs both, so make this file self-sufficient on a fresh database.
CREATE SCHEMA IF NOT EXISTS src_gmail;
CREATE EXTENSION IF NOT EXISTS citext;

-- ── Cursor table takes the name the doc uses ─────────────────────────────────
-- The doc calls this table src_gmail.sync_state (Task 5: "stays EXACTLY as
-- built"; Task 6: "checkpoint sync_state.history_id"). Two tables were in the
-- way of that name:
--
--   src_gmail.sync_state      mailbox · history_id · last_internal_date_ms
--                             last_message_id · last_synced_at
--                             DEAD — cursor of the deleted ticket-sync
--                             pipeline. Not written since 2026-08-12.
--
--   src_gmail.raw_sync_state  account_id · history_id · backfill_done
--                             backfill_page_token · last_synced_at
--                             watch_expiration_ms
--                             LIVE — the raw pipeline's cursor
--
-- So: park the dead one under sync_state_legacy, then give the live one the
-- doc's name. A rename rather than a DROP — the legacy row is the only record
-- of where the old pipeline stopped, it costs one row to keep, and a migration
-- should not be the thing that destroys data. Drop sync_state_legacy by hand
-- once nobody wants it.
--
-- Both steps are guarded on the shape, not just the name, so this file stays
-- re-runnable and is a no-op on a database that never had the old pipeline.
DO $$
BEGIN
    -- 1. Vacate the name, keeping the dead cursor's data.
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'src_gmail'
                  AND table_name = 'sync_state'
                  AND column_name = 'mailbox')          -- the legacy shape
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'src_gmail'
                          AND table_name = 'sync_state_legacy')
    THEN
        ALTER TABLE src_gmail.sync_state RENAME TO sync_state_legacy;
        RAISE NOTICE 'parked dead ticket-sync cursor as src_gmail.sync_state_legacy';
    END IF;

    -- 2. Live cursor takes the doc's name. Design unchanged — only the name.
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'src_gmail' AND table_name = 'raw_sync_state')
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'src_gmail' AND table_name = 'sync_state')
    THEN
        ALTER TABLE src_gmail.raw_sync_state RENAME TO sync_state;
        RAISE NOTICE 'renamed raw_sync_state -> sync_state (doc name)';
    END IF;
END $$;

-- ── The old grain goes ───────────────────────────────────────────────────────
DROP TABLE IF EXISTS src_gmail.tickets;

-- ── mailbox ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS src_gmail.mailbox (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL,
    source_system      text NOT NULL DEFAULT 'gmail',
    external_id        text NOT NULL,
    address            citext NOT NULL,
    is_synthetic       boolean NOT NULL DEFAULT false,
    connector_run_id   uuid NOT NULL,
    observed_at        timestamptz NOT NULL,
    valid_from         timestamptz NOT NULL,
    UNIQUE (tenant_id, source_system, external_id)
);

-- ── thread ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS src_gmail.thread (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               uuid NOT NULL,
    source_system           text NOT NULL DEFAULT 'gmail',
    external_id             text NOT NULL,          -- gmail threadId
    mailbox_id              uuid NOT NULL REFERENCES src_gmail.mailbox(id),
    message_count           int NOT NULL DEFAULT 0,
    first_internal_date_ms  bigint,
    last_internal_date_ms   bigint,
    is_synthetic            boolean NOT NULL DEFAULT false,
    connector_run_id        uuid NOT NULL,
    observed_at             timestamptz NOT NULL,
    valid_from              timestamptz NOT NULL,
    UNIQUE (tenant_id, source_system, external_id)
);

-- ── message ──────────────────────────────────────────────────────────────────
-- Only the object path and checksum live here; the payload itself stays in
-- MinIO. external_id (the Gmail message id) is the dedup key.
CREATE TABLE IF NOT EXISTS src_gmail.message (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL,
    source_system       text NOT NULL DEFAULT 'gmail',
    external_id         text NOT NULL,              -- gmail messageId = DEDUP KEY
    thread_id           uuid NOT NULL REFERENCES src_gmail.thread(id),
    mailbox_id          uuid NOT NULL REFERENCES src_gmail.mailbox(id),
    subject             text,
    from_address        citext,
    from_display_name   text,
    reply_to            citext,
    to_addresses        text[],
    cc_addresses        text[],
    in_reply_to         text,
    references_header   text,
    list_id             text,
    body_text           text,                       -- quotes stripped
    body_html_present   boolean NOT NULL DEFAULT false,
    quoted_stripped     boolean NOT NULL DEFAULT false,
    signature_block     text,                       -- KEEP: identity signal
    object_path         text NOT NULL,
    checksum_sha256     text NOT NULL,
    internal_date_ms    bigint NOT NULL,
    history_id          text,
    label_ids           text[],
    is_synthetic        boolean NOT NULL DEFAULT false,
    connector_run_id    uuid NOT NULL,
    observed_at         timestamptz NOT NULL,
    valid_from          timestamptz NOT NULL,
    UNIQUE (tenant_id, source_system, external_id)
);
CREATE INDEX IF NOT EXISTS idx_message_thread ON src_gmail.message (thread_id);
CREATE INDEX IF NOT EXISTS idx_message_from   ON src_gmail.message (from_address);

-- ── attachment ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS src_gmail.attachment (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL,
    source_system      text NOT NULL DEFAULT 'gmail',
    external_id        text NOT NULL,               -- gmail attachmentId
    message_id         uuid NOT NULL REFERENCES src_gmail.message(id),
    filename           text,
    mime_type          text,
    size_bytes         bigint,
    object_path        text NOT NULL,
    checksum_sha256    text NOT NULL,
    is_synthetic       boolean NOT NULL DEFAULT false,
    connector_run_id   uuid NOT NULL,
    observed_at        timestamptz NOT NULL,
    valid_from         timestamptz NOT NULL,
    UNIQUE (tenant_id, source_system, external_id)
);
CREATE INDEX IF NOT EXISTS idx_attachment_message ON src_gmail.attachment (message_id);
