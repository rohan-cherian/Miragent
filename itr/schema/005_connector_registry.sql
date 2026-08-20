-- itr/schema/005_connector_registry.sql
-- Which source connectors exist, and when each last ran.
-- Apply: poetry run python scripts/load_gmail_schema.py
--
-- Backs GET /api/v1/connections (Task 24) and the console's Source Catalogue.
-- The Slice-1 doc's demo mapping names "connector_registry + raw_ingest.runs"
-- as that endpoint's source, but no task's SQL creates the registry — Task 6
-- defines runs and run_stage_event only. scout/api/routes/connections.py was
-- written against an assumed table and documented as blocked on Task 6, so
-- this file closes that gap on the source side where the registry belongs.
--
-- Slot 005 was the one number left free between the Gmail raw tables (002-004)
-- and the canonical layer (006-009).
--
-- last_synced_at is DERIVED, not stored twice: the view below reads it from
-- raw_ingest.runs so the registry cannot drift from what actually ran.

CREATE SCHEMA IF NOT EXISTS raw_ingest;

CREATE TABLE IF NOT EXISTS raw_ingest.connector_registry (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system  text NOT NULL UNIQUE,
    display_name   text NOT NULL,
    subtitle       text,
    status         text NOT NULL DEFAULT 'disconnected',  -- connected | disconnected | error
    -- Gmail is the one real source in Slice 1; every other system is emulated.
    is_emulated    boolean NOT NULL DEFAULT true,
    rate_limit_line text,
    last_synced_at timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_connector_registry_source
    ON raw_ingest.connector_registry (source_system);

-- The connectors Slice 1 knows about. Only Gmail is real; the rest are the
-- emulators, registered so the Source Catalogue shows the full estate rather
-- than pretending Gmail is the whole system.
INSERT INTO raw_ingest.connector_registry
    (source_system, display_name, subtitle, status, is_emulated, rate_limit_line)
VALUES
    ('gmail',      'Gmail',           'Customer support mailbox',    'connected',    false,
     '250 quota units/user/second'),
    ('zendesk',    'Zendesk',         'Ticketing (emulated)',        'disconnected', true,
     '700 requests/minute'),
    ('workday',    'Workday',         'HR / worker data (emulated)', 'disconnected', true,
     'RaaS: 10 concurrent reports')
ON CONFLICT (source_system) DO UPDATE SET
    display_name    = EXCLUDED.display_name,
    subtitle        = EXCLUDED.subtitle,
    is_emulated     = EXCLUDED.is_emulated,
    rate_limit_line = EXCLUDED.rate_limit_line;

-- Keep last_synced_at honest: derive it from the newest successful run rather
-- than writing it in two places and letting them disagree.
CREATE OR REPLACE VIEW raw_ingest.connector_status AS
SELECT
    r.id,
    r.source_system,
    r.display_name,
    r.subtitle,
    r.status,
    r.is_emulated,
    r.rate_limit_line,
    (SELECT max(finished_at) FROM raw_ingest.runs run
      WHERE run.source_system = r.source_system AND run.status = 'success') AS last_synced_at
FROM raw_ingest.connector_registry r;
