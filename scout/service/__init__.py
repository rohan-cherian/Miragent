"""
W1-API-01 — Miragent console FastAPI service skeleton.

App factory, DI, health/ready probes, /corpus/stats (live Postgres),
CORS for the console, OpenAPI, and a single error envelope.
"""

from scout.service.app import create_app

__all__ = ["create_app"]
