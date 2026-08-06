.PHONY: up down reset status seed

# Bring everything up and block until every service reports healthy.
# Prints the total time taken — this is the number that goes on the board.
up:
	@if [ ! -f .env ]; then \
		echo "No .env found. Copy .env.example to .env first: cp .env.example .env"; \
		exit 1; \
	fi
	@echo "Starting stack..."
	@START=$$(date +%s); \
	docker compose up -d --wait --wait-timeout 180; \
	END=$$(date +%s); \
	echo "All services healthy. Startup time: $$((END-START))s"

# Tear everything down, including named volumes (full reset).
reset:
	@echo "Tearing down stack and removing volumes..."
	docker compose down -v --remove-orphans
	@echo "Done. Run 'make up' for a clean start."

# Stop containers without removing volumes.
down:
	docker compose down

# Show current health status of every service.
status:
	docker compose ps

# Placeholder — reference data + smoke corpus load (Step 6, Sutej's doc).
# Wire this to the actual seeding script once it exists.
seed:
	@echo "TODO: load reference data + ~200 ticket smoke corpus (must finish < 10 min)"
