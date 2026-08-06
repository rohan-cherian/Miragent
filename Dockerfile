FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==1.8.3

# Copy dependency files first (layer cache)
COPY pyproject.toml poetry.lock ./

# Install Python dependencies (no dev deps, no virtualenv — we're in a container)
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copy application code
COPY scout/ ./scout/
COPY scripts/ ./scripts/

# Non-root user for security
RUN useradd -m -u 1001 miragent && chown -R miragent:miragent /app
USER miragent

EXPOSE 8000

CMD ["uvicorn", "scout.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
