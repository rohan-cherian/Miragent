# ITR Scout Agent — Slice 1
# Task 3 — developer workflow targets.
#
# Run `make <target>` from this directory (itr/). Targets that depend on
# scripts or setup that don't exist yet report a clear "not yet
# implemented" message instead of failing — that's expected while the
# rest of Slice 1 is still being built.

COMPOSE_FILE := infra/docker-compose.yml
ENV_FILE := .env.local

.PHONY: up migrate seed gmail-backfill gmail-sync gmail-fixtures ingest reconcile api e2e reset

# Start the local infra stack (Postgres, Qdrant, Neo4j, Redis) and wait
# until every service reports healthy before returning.
up:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --wait --wait-timeout 180

# Apply database schema: run schema/*.sql files in numeric order, then
# run Alembic migrations. Both pieces are optional right now — if
# either isn't set up yet, this reports what's missing and skips
# instead of failing.
migrate:
	@sql_files="$$(ls schema/*.sql 2>/dev/null | sort)"; \
	if [ -z "$$sql_files" ] || [ ! -f alembic.ini ]; then \
		echo "No schema/*.sql files or alembic setup found yet - skipping"; \
	else \
		for f in $$sql_files; do \
			echo "Applying $$f..."; \
			docker exec -i itr_postgres psql -U postgres -d itr -v ON_ERROR_STOP=1 < $$f; \
		done; \
		poetry run alembic upgrade head; \
	fi

# Load reference data: personas and taxonomy. Each script is checked
# and run independently, so one missing script doesn't block the other.
seed:
	@if [ -f scripts/seed_personas.py ]; then \
		poetry run python scripts/seed_personas.py; \
	else \
		echo "scripts/seed_personas.py not yet implemented - skipping"; \
	fi
	@if [ -f scripts/seed_taxonomy.py ]; then \
		poetry run python scripts/seed_taxonomy.py; \
	else \
		echo "scripts/seed_taxonomy.py not yet implemented - skipping"; \
	fi

# Full historical Gmail pull. Uses gmail_sync_once.py's --max flag with
# a large value to pull a large backlog in one run — there's no
# separate --backfill flag yet, so this is the closest equivalent.
gmail-backfill:
	@if [ -f scripts/gmail_sync_once.py ]; then \
		poetry run python scripts/gmail_sync_once.py --max 1000; \
	else \
		echo "scripts/gmail_sync_once.py not yet implemented - skipping"; \
	fi

# Regular incremental Gmail sync (one run, default page size).
gmail-sync:
	@if [ -f scripts/gmail_sync_once.py ]; then \
		poetry run python scripts/gmail_sync_once.py; \
	else \
		echo "scripts/gmail_sync_once.py not yet implemented - skipping"; \
	fi

# Export a Gmail fixture set for offline/test use.
gmail-fixtures:
	@if [ -f scripts/export_fixtures.py ]; then \
		poetry run python scripts/export_fixtures.py; \
	else \
		echo "scripts/export_fixtures.py not yet implemented - skipping"; \
	fi

# Ingest source data into the canonical (itr360) schema.
ingest:
	@if [ -f scripts/ingest_canonical.py ]; then \
		poetry run python scripts/ingest_canonical.py; \
	else \
		echo "scripts/ingest_canonical.py not yet implemented - pending Task 13"; \
	fi

# Check the completeness table and reconcile any gaps.
reconcile:
	@if [ -f scripts/reconcile.py ]; then \
		poetry run python scripts/reconcile.py; \
	else \
		echo "scripts/reconcile.py not yet implemented - pending Task 16"; \
	fi

# Run the FastAPI console/service locally with autoreload. Meant to be
# run manually by a developer — no existence check, so it fails
# naturally (and clearly) if scout/api/app.py isn't built yet.
api:
	poetry run uvicorn scout.api.app:app --reload

# Run the full test suite as a stand-in acceptance run. Point this at
# scripts/e2e_report.py instead once a proper e2e report script exists.
e2e:
	poetry run pytest

# Full teardown: stop and remove containers and named volumes.
reset:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down -v
