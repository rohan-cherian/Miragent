"""
FastAPI app for ITR Slice 1 ingestion.

Hosts the Gmail push receiver. Run with:
    poetry run uvicorn scout.api.app:create_app --factory --reload --port 8092
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from scout.api.routes.gmail_push import router as gmail_router
from scout.config import settings


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(
        title="ITR Ingestion API",
        version="0.1.0",
        description="Gmail push receiver and raw-lake ingestion triggers.",
    )
    app.include_router(gmail_router)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "bucket": settings.minio_bucket,
            "endpoint": settings.minio_endpoint,
        }

    return app
