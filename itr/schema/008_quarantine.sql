-- schema/008_quarantine.sql
--
-- Task 16 — raw_ingest.quarantine. A dead row that vanishes is a bug
-- that vanishes with it: rows here are never deleted, only advanced
-- (pending -> retrying -> dead) or manually resolved.
--
-- NOTE on <provenance>: the Task 16 spec lists connector_run_id,
-- source_system, and external_id as explicit named columns ahead of
-- the <provenance> placeholder — those three are already part of the
-- Provenance mixin's column set, so expanding <provenance> to the
-- FULL mixin here would duplicate them. This file expands it to only
-- the remaining Provenance fields: tenant_id, is_synthetic,
-- observed_at, valid_from. The SQLAlchemy model (Quarantine, in
-- scout/canonical/models.py) doesn't have this problem — it inherits
-- Provenance normally and gets all seven fields once, same as every
-- other model in this codebase.

CREATE TABLE raw_ingest.quarantine (
  id uuid PRIMARY KEY,
  connector_run_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  object_path text,                 -- raw ALWAYS retained (e.g. MinIO key)
  error_code text NOT NULL,         -- e.g. GM-ERR-1021
  error_reason text NOT NULL,       -- human-readable, e.g. 'invalid email format'
  retry_count int NOT NULL DEFAULT 0,
  max_retries int NOT NULL DEFAULT 5,
  status text NOT NULL,             -- pending|retrying|dead|resolved
  first_seen_at timestamptz NOT NULL,
  last_attempt_at timestamptz,

  tenant_id uuid NOT NULL,
  is_synthetic boolean NOT NULL DEFAULT false,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_raw_ingest_quarantine_tenant_id ON raw_ingest.quarantine (tenant_id);
