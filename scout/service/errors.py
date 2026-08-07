"""Consistent error envelope for every console API endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_body(
    *,
    code: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    """
    Single envelope used by all endpoints::

        {
          "error": {
            "code": "not_found",
            "message": "…",
            "details": null
          }
        }
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(code=code, message=message, details=details),
    )


class AppError(Exception):
    """Raise inside handlers; converted to the standard envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Any = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    """Wire AppError / HTTP / validation / unhandled → same envelope."""

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            429: "rate_limited",
            500: "internal_error",
            503: "service_unavailable",
        }
        code = code_map.get(exc.status_code, "http_error")
        detail = exc.detail
        if isinstance(detail, str):
            message = detail
            details = None
        else:
            message = "Request failed"
            details = detail
        return error_response(
            status_code=exc.status_code,
            code=code,
            message=message,
            details=details,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred",
            details=str(exc) if app.debug else None,
        )
