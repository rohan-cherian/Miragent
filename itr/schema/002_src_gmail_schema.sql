-- src_gmail — email → ticket store (Gmail sync Phases 5–6)
-- Apply: poetry run python scripts/load_gmail_schema.py

CREATE SCHEMA IF NOT EXISTS src_gmail;

CREATE TABLE IF NOT EXISTS src_gmail.sync_state (
    mailbox               TEXT PRIMARY KEY,
    history_id            TEXT,
    last_internal_date_ms BIGINT,
    last_message_id       TEXT,
    last_synced_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS src_gmail.tickets (
    ticket_id             BIGSERIAL PRIMARY KEY,
    gmail_message_id      TEXT NOT NULL,
    gmail_thread_id       TEXT NOT NULL,
    mailbox               TEXT NOT NULL,
    subject               TEXT NOT NULL,
    description           TEXT NOT NULL DEFAULT '',
    from_address          TEXT,
    to_address            TEXT,
    bookmark              TEXT,
    internal_date_ms      BIGINT,
    history_id            TEXT,
    synced_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gmail_tickets_message_id UNIQUE (gmail_message_id)
);

CREATE INDEX IF NOT EXISTS idx_gmail_tickets_mailbox_date
    ON src_gmail.tickets (mailbox, internal_date_ms DESC);

CREATE INDEX IF NOT EXISTS idx_gmail_tickets_thread
    ON src_gmail.tickets (gmail_thread_id);
