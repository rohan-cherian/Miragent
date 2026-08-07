"""
W1-API-01 — FastAPI application factory.

Creates the console API with:
  - dependency injection (settings + Database on app.state)
  - /health and /ready probes
  - /corpus/stats live Postgres aggregates
  - OpenAPI at /docs
  - CORS for the console
  - one consistent error envelope
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scout.service.config import ServiceSettings, get_settings
from scout.service.db import Database
from scout.service.errors import register_exception_handlers
from scout.service.routes import router


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    """
    Application factory — call from uvicorn::

        uvicorn scout.service.app:create_app --factory --port 8090
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        url = settings.resolved_database_url()
        app.state.settings = settings
        app.state.db = Database(url) if url else None
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Miragent console API — single door for console screens and agents. "
            "W1-API-01 skeleton: health, ready, corpus stats."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(router)
    return app
