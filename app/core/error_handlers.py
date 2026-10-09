"""Global exception handlers producing the standard JSON error response.

Every error body has the shape::

    {"status_code": 404, "error_code": 1001, "message": "...", "error": null}

`message` is safe to show to users; `error` carries structured details (e.g.
validation fields) or `null`. Tracebacks, SQL and driver messages are logged,
never returned.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppException, ErrorCode
from app.core.metrics import record_exception

logger = logging.getLogger("app.errors")

_STATUS_ERROR_CODES: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.BAD_REQUEST,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCode.VALIDATION_ERROR,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
}

_STATUS_MESSAGES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "Bad request",
    status.HTTP_401_UNAUTHORIZED: "Could not validate credentials",
    status.HTTP_403_FORBIDDEN: "Forbidden",
    status.HTTP_404_NOT_FOUND: "Not found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed",
    status.HTTP_409_CONFLICT: "Conflict",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "Validation error",
    status.HTTP_429_TOO_MANY_REQUESTS: "Too many requests",
    status.HTTP_503_SERVICE_UNAVAILABLE: "Service unavailable",
}

_VALUE_ERROR_PREFIX = "Value error, "


class ErrorResponse(BaseModel):
    """Body of every error response."""

    status_code: int
    error_code: int
    message: str
    error: Any = None


def error_response(
    *,
    status_code: int,
    error_code: int,
    message: str,
    error: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        status_code=status_code,
        error_code=int(error_code),
        message=message,
        error=error,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, str]]:
    """Keep field, message and type only; drop `input`/`ctx` so values never echo back."""
    sanitized: list[dict[str, str]] = []
    for err in errors:
        message = str(err.get("msg", "Invalid value"))
        if message.startswith(_VALUE_ERROR_PREFIX):
            message = message[len(_VALUE_ERROR_PREFIX) :]
        sanitized.append(
            {
                "field": ".".join(str(part) for part in err.get("loc", ())),
                "message": message,
                "type": str(err.get("type", "value_error")),
            }
        )
    return sanitized


def _request_label(request: Request) -> str:
    return f"{request.method} {request.url.path}"


async def app_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppException)
    record_exception(exc.error_code.name, "app")
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error(
            "%s failed: %s (%s) %s",
            _request_label(request),
            exc.error_code.name,
            exc.message,
            exc.log_detail or "",
            exc_info=exc if exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR else None,
        )
    else:
        logger.info(
            "%s -> %s %s%s",
            _request_label(request),
            exc.status_code,
            exc.error_code.name,
            f" ({exc.log_detail})" if exc.log_detail else "",
        )
    return error_response(
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
        error=exc.error,
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status_code = exc.status_code
    error_code = _STATUS_ERROR_CODES.get(
        status_code,
        ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.BAD_REQUEST,
    )
    record_exception(error_code.name, "http")
    default_message = _STATUS_MESSAGES.get(status_code, "Request failed")
    if isinstance(exc.detail, str) and exc.detail:
        message, error = exc.detail, None
    else:
        message, error = default_message, exc.detail

    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.warning("%s -> %s %s", _request_label(request), status_code, message)
    else:
        logger.info("%s -> %s %s", _request_label(request), status_code, error_code.name)
    return error_response(
        status_code=status_code,
        error_code=error_code,
        message=message,
        error=error,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    record_exception(type(exc).__name__, "validation")
    errors = sanitize_validation_errors(exc.errors())
    logger.info(
        "%s -> 422 VALIDATION_ERROR fields=%s",
        _request_label(request),
        [e["field"] for e in errors],
    )
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_code=ErrorCode.VALIDATION_ERROR,
        message="Validation error",
        error=errors,
    )


async def integrity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    record_exception(type(exc).__name__, "integrity")
    logger.warning("%s -> 409 integrity error: %s", _request_label(request), exc)
    return error_response(
        status_code=status.HTTP_409_CONFLICT,
        error_code=ErrorCode.DUPLICATE_RESOURCE,
        message="Resource already exists",
    )


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    record_exception(type(exc).__name__, "database")
    logger.error("%s database error", _request_label(request), exc_info=exc)
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code=ErrorCode.DATABASE_ERROR,
        message="Database error",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    record_exception(type(exc).__name__, "unhandled")
    logger.error("%s unhandled exception", _request_label(request), exc_info=exc)
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code=ErrorCode.INTERNAL_ERROR,
        message="Internal server error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
