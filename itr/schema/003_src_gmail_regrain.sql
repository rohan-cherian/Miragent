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

-- ── Cursor table: NOT renamed, deliberately ──────────────────────────────────
-- The doc says "src_gmail.sync_state stays EXACTLY as built" and Task 6 refers
-- to sync_state.history_id. Both refer to a table that still physically exists
-- in this database but belongs to the DELETED ticket-sync pipeline:
--
--   src_gmail.sync_state      mailbox · history_id · last_internal_date_ms
--                             last_message_id · last_synced_at
--                             1 stale row, last written 2026-08-12
--
--   src_gmail.raw_sync_state  account_id · history_id · backfill_done
--                             backfill_page_token · last_synced_at
--                             watch_expiration_ms
--                             LIVE — this is the cursor the raw pipeline uses
--
-- They are different shapes, so raw_sync_state cannot simply take the other's
-- name while it is occupied, and dropping a table with data is not something
-- to do inside a migration without a human deciding. Left alone; the raw
-- pipeline keeps using raw_sync_state until that call is made.

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
