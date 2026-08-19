-- schema/007_person_email_alias.sql
--
-- Task 11 — person_email_alias.
--
-- Consumer Gmail addresses match nothing in a corporate directory, so
-- the identity hop and org association have to come from THIS table,
-- not from itr360.person.primary_email. Provenance columns match
-- scout/canonical/models.py's Provenance mixin exactly (see
-- schema/006_canonical_itr360_tables.sql for the full column list).

CREATE TABLE itr360.person_email_alias (
  id uuid PRIMARY KEY,
  person_id uuid NOT NULL REFERENCES itr360.person(id),
  email citext NOT NULL,
  email_kind text NOT NULL,        -- personal | corporate | alias
  verified boolean NOT NULL DEFAULT false,
  verified_by text,
  verified_at timestamptz,
  confidence numeric(3,2),
  evidence jsonb NOT NULL,

  tenant_id uuid NOT NULL,
  source_system text NOT NULL,
  external_id text,
  is_synthetic boolean NOT NULL DEFAULT false,
  connector_run_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,

  UNIQUE (tenant_id, email)
);
CREATE INDEX ix_itr360_person_email_alias_tenant_id ON itr360.person_email_alias (tenant_id);
CREATE INDEX ON itr360.person_email_alias (tenant_id, email);
