-- itr/schema/004_raw_ingest.sql
-- Slice-1 Task 6 — raw landing + run tracking · ROHAN
-- Apply: poetry run python scripts/load_gmail_schema.py
--
-- raw_ingest.runs.id IS the connector_run_id stamped on every src_gmail row, so
-- any row traces back to the run that wrote it, and any run can be replayed.
--
-- run_stage_event is what makes the demo's Pipeline Scan screen real rather
-- than a hardcoded animation: progress bars read progress_pct, the mini-logs
-- read log_line, and the timeline reads duration_ms.
--
-- Lives in the same database as src_gmail so runs and messages stay joinable —
-- infra/init-schemas.sql also declares raw_ingest in the itr database, which is
-- harmless: whichever database a connector writes to gets its own runs.

CREATE SCHEMA IF NOT EXISTS raw_ingest;

CREATE TABLE IF NOT EXISTS raw_ingest.runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),  -- = connector_run_id
    tenant_id         uuid NOT NULL,
    source_system     text NOT NULL,
    mode              text NOT NULL,   -- backfill | history | fixtures | canonical
    started_at        timestamptz NOT NULL,
    finished_at       timestamptz,
    status            text NOT NULL,   -- running | success | failed | partial
    cursor_before     text,
    cursor_after      text,
    messages_seen     int NOT NULL DEFAULT 0,
    messages_written  int NOT NULL DEFAULT 0,
    messages_skipped  int NOT NULL DEFAULT 0,
    errors            jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON raw_ingest.runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_source_status ON raw_ingest.runs (source_system, status);

-- drives the demo's 7-stage progress bars and mini-logs
CREATE TABLE IF NOT EXISTS raw_ingest.run_stage_event (
    id            bigserial PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES raw_ingest.runs(id),
    stage         text NOT NULL,       -- connect|discover|extract|redact|normalise|resolve|index
    progress_pct  int NOT NULL,        -- 0..100
    log_line      text NOT NULL,
    duration_ms   int,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stage_event_run ON raw_ingest.run_stage_event (run_id, created_at);
