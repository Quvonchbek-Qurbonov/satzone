from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for application-level errors raised by services."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "app_error"
    message: str = "Application error"

    def __init__(self, message: str | None = None, *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.code = code or self.code
        self.details = details


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource conflict"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"
    message = "Authentication required"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "Operation not permitted"


class ValidationAppError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"
    message = "Validation failed"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests"


def _error_payload(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Preserve detail (string or dict) but normalize shape
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        details = None if isinstance(exc.detail, str) else exc.detail
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, message, details),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic v2 may stash a ValueError instance under each error's `ctx`,
        # which json.dumps cannot serialize — run errors through jsonable_encoder.
        details = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_payload("validation_error", "Request validation failed", details),
        )

    @app.exception_handler(IntegrityError)
    async def _handle_integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("integrity_error", error=str(exc.orig))
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_error_payload("conflict", "Resource conflict"),
        )

    @app.exception_handler(SQLAlchemyError)
    async def _handle_sqla(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("database_error", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload("database_error", "A database error occurred"),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload("internal_error", "Internal server error"),
        )

    # Used internally where HTTPException is more natural (e.g. dependencies)
    @app.exception_handler(HTTPException)
    async def _handle_fastapi_http(_: Request, exc: HTTPException) -> JSONResponse:
        return await _handle_http_exception(_, exc)