-- itr/infra/init-schemas.sql
-- Runs once on first Postgres container startup (docker-entrypoint-initdb.d).
-- Creates schema namespaces only — no tables yet. Tables land later as
-- separate migrations when each schema actually starts being used.
--
-- itr360 is the existing canonical schema name — do not rename to "itr".

CREATE SCHEMA IF NOT EXISTS raw_ingest;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS itr360;
CREATE SCHEMA IF NOT EXISTS agent_ops;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE EXTENSION IF NOT EXISTS vector;
