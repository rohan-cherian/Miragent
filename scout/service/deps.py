"""FastAPI dependency injection for the console API."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from scout.service.config import ServiceSettings, get_settings
from scout.service.db import Database
from scout.service.errors import AppError


def get_service_settings() -> ServiceSettings:
    return get_settings()


def get_database(request: Request) -> Database:
    """
    Resolve the Database from app state (created in the factory).

    Raises 503 if the app was started without a DSN.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise AppError(
            "misconfigured",
            "Database is not configured on this application",
            status_code=503,
        )
    return db


SettingsDep = Annotated[ServiceSettings, Depends(get_service_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
