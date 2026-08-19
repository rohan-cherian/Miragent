-- schema/006_canonical_itr360_tables.sql
--
-- Task 10 — canonical itr360 tables.
--
-- Provenance columns (repeated on every table below that carries them,
-- matching scout/canonical/models.py's Provenance mixin exactly):
--   tenant_id uuid NOT NULL, source_system text NOT NULL,
--   external_id text, is_synthetic boolean NOT NULL DEFAULT false,
--   connector_run_id uuid NOT NULL, observed_at timestamptz NOT NULL,
--   valid_from timestamptz NOT NULL
--
-- case_event and decision_audit do NOT carry Provenance — they are pure
-- append-only event logs. problem_taxonomy is a static reference table
-- (the classifier's fixed label space, not connector-ingested data) and
-- also does not carry Provenance.
--
-- Several FK-shaped columns below intentionally have no REFERENCES
-- clause (e.g. case_event.case_id, triage_result.message_id,
-- recommendation_decision.case_id / proposed_action_id,
-- write_execution.case_id) — this matches the table definitions given
-- in the Task 10 spec exactly, not an oversight.

CREATE EXTENSION IF NOT EXISTS citext;

-- ─────────────────────────────────────────────────────────
-- org
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.org (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  tier text,
  domain text,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_itr360_org_tenant_id ON itr360.org (tenant_id);

-- ─────────────────────────────────────────────────────────
-- person
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.person (
  id uuid PRIMARY KEY,
  org_id uuid REFERENCES itr360.org(id),
  display_name text NOT NULL,
  primary_email citext,
  job_title text,
  department text,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_itr360_person_tenant_id ON itr360.person (tenant_id);

-- ─────────────────────────────────────────────────────────
-- case_ (trailing underscore — "case" is a reserved word)
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.case_ (
  id uuid PRIMARY KEY,
  case_number text NOT NULL,             -- format ITR-{year}-{seq:05d}
  org_id uuid REFERENCES itr360.org(id),
  requester_id uuid REFERENCES itr360.person(id),
  subject text NOT NULL,
  status text NOT NULL,                  -- CaseStatus enum
  priority text,
  intent_class text,
  opened_at timestamptz NOT NULL,
  closed_at timestamptz,
  reopened_count int NOT NULL DEFAULT 0,
  related_case_ids uuid[] NOT NULL DEFAULT '{}',

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,

  UNIQUE (tenant_id, case_number)
);
CREATE INDEX ix_itr360_case__tenant_id ON itr360.case_ (tenant_id);

-- ─────────────────────────────────────────────────────────
-- message
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.message (
  id uuid PRIMARY KEY,
  case_id uuid NOT NULL REFERENCES itr360.case_(id),
  person_id uuid REFERENCES itr360.person(id),
  direction text NOT NULL,               -- inbound | outbound
  channel text NOT NULL DEFAULT 'email',
  subject text,
  body_redacted text NOT NULL,           -- ONLY redacted text is ever stored
  pii_map jsonb,
  pii_status text NOT NULL,
  src_message_id uuid NOT NULL,          -- pointer into src_gmail.message
  sent_at timestamptz NOT NULL,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_itr360_message_tenant_id ON itr360.message (tenant_id);

-- ─────────────────────────────────────────────────────────
-- case_event — append only, no Provenance
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.case_event (
  id uuid PRIMARY KEY,
  case_id uuid NOT NULL,
  event_type text NOT NULL,
  payload jsonb,
  occurred_at timestamptz NOT NULL,
  actor text
);

-- ─────────────────────────────────────────────────────────
-- problem_taxonomy — static reference table, no Provenance
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.problem_taxonomy (
  id uuid PRIMARY KEY,
  category text NOT NULL,                -- 10 of these
  problem_class text NOT NULL,           -- 100 of these
  description text,
  example_phrases text[],
  default_priority text,
  UNIQUE (category, problem_class)
);

-- ─────────────────────────────────────────────────────────
-- triage_result — MVP PHASE 1 HEADLINE OUTPUT
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.triage_result (
  id uuid PRIMARY KEY,
  case_id uuid NOT NULL REFERENCES itr360.case_(id),
  message_id uuid NOT NULL,
  intent_class text,
  category text,
  sub_category text,
  priority text,                         -- deterministic, not the LLM
  urgency_signals jsonb,
  sentiment text,
  confidence numeric(3,2) NOT NULL,
  band text NOT NULL,                    -- high|medium|low|needs_human_triage
  rationale text NOT NULL,               -- must quote the email
  evidence_spans jsonb,                  -- [{start,end,text}]
  model_name text NOT NULL,
  prompt_version text NOT NULL,
  tier_used text NOT NULL,
  latency_ms int,
  tokens_in int,
  tokens_out int,
  cost_usd numeric(10,6),
  version int NOT NULL DEFAULT 1,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_itr360_triage_result_tenant_id ON itr360.triage_result (tenant_id);

-- ─────────────────────────────────────────────────────────
-- proposed_action
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.proposed_action (
  id uuid PRIMARY KEY,
  case_id uuid NOT NULL REFERENCES itr360.case_(id),
  triage_result_id uuid REFERENCES itr360.triage_result(id),
  resolution_path text,
  recommended_action_text text NOT NULL,
  draft_sentences jsonb NOT NULL,        -- [{text, citation_refs[], withheld:bool}]
  confidence numeric(3,2),
  risk text,
  recommended_owner text,
  evidence jsonb NOT NULL,               -- [Citation DTO]
  policy_ref text,
  approval_required boolean NOT NULL DEFAULT true,
  model_name text NOT NULL,
  prompt_version text NOT NULL,
  version int NOT NULL DEFAULT 1,
  version_token text NOT NULL,
  status text NOT NULL,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_itr360_proposed_action_tenant_id ON itr360.proposed_action (tenant_id);

-- ─────────────────────────────────────────────────────────
-- recommendation_decision and write_execution are TWO SEPARATE
-- TABLES. Do not merge them: an approval being recorded is not the
-- same event as a write succeeding.
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.recommendation_decision (
  id uuid PRIMARY KEY,
  case_id uuid NOT NULL,
  proposed_action_id uuid NOT NULL,
  state text NOT NULL,                   -- DecisionState enum
  edited_text text,
  edit_diff jsonb,
  reject_reason text,
  payload_hash text NOT NULL,
  actor text NOT NULL,
  decided_at timestamptz NOT NULL,
  version_token text NOT NULL,
  idempotency_key text,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,

  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX ix_itr360_recommendation_decision_tenant_id ON itr360.recommendation_decision (tenant_id);

CREATE TABLE itr360.write_execution (
  id uuid PRIMARY KEY,
  decision_id uuid NOT NULL REFERENCES itr360.recommendation_decision(id),
  case_id uuid NOT NULL,
  action_type text NOT NULL,             -- GMAIL_SEND_REPLY
  state text NOT NULL,                   -- WriteState enum
  attempts int NOT NULL DEFAULT 0,
  execution_ref text,                    -- returned gmail message id
  suppressed_reason text,                -- 'ACTION_MODE=draft_only'
  error text,
  started_at timestamptz,
  finished_at timestamptz,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_itr360_write_execution_tenant_id ON itr360.write_execution (tenant_id);

-- ─────────────────────────────────────────────────────────
-- identity_unresolved_queue
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.identity_unresolved_queue (
  id uuid PRIMARY KEY,
  src_message_id uuid NOT NULL,
  sender_email citext NOT NULL,
  sender_display text,
  best_guess_person_id uuid REFERENCES itr360.person(id),
  best_confidence numeric(3,2),
  evidence jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending',   -- pending|resolved|dismissed
  resolved_by text,
  resolved_at timestamptz,
  dismiss_reason text,
  created_at timestamptz NOT NULL,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL
);
CREATE INDEX ix_itr360_identity_unresolved_queue_tenant_id ON itr360.identity_unresolved_queue (tenant_id);

-- ─────────────────────────────────────────────────────────
-- decision_audit — APPEND ONLY. No Provenance (has its own tenant_id).
-- Column set matches scout/governance/audit.py's Core Table exactly:
-- id, tenant_id, case_id, actor, action, category, inputs, outputs,
-- confidence, trace_id, created_at.
-- ─────────────────────────────────────────────────────────
CREATE TABLE itr360.decision_audit (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  case_id uuid,
  actor text NOT NULL,
  action text NOT NULL,
  category text NOT NULL,   -- scan|identity|redaction|approval|system
  inputs jsonb,
  outputs jsonb,
  confidence numeric(3,2),
  trace_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE ON itr360.decision_audit FROM PUBLIC;
CREATE INDEX ON itr360.decision_audit (category, created_at DESC);
