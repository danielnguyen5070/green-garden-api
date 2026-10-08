"""Application exception hierarchy and error codes.

Every error the API returns on purpose is an `AppException`. Its `message` is
sent to the client as-is, so it must never contain SQL, driver output, tokens
or other internals; put those in `log_detail`, which is only logged.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from fastapi import status


class ErrorCode(IntEnum):
    """Stable machine-readable codes returned as `error_code`."""

    # 1000-1099: resource not found
    NOT_FOUND = 1000
    CUSTOMER_NOT_FOUND = 1001
    ADMIN_NOT_FOUND = 1002
    CATEGORY_NOT_FOUND = 1003
    PLANT_NOT_FOUND = 1004
    PLANT_IMAGE_NOT_FOUND = 1005
    PLANT_POT_SIZE_NOT_FOUND = 1006
    ORDER_NOT_FOUND = 1007
    REVIEW_NOT_FOUND = 1008
    NOTIFICATION_NOT_FOUND = 1009
    POT_SIZE_UNAVAILABLE = 1010

    # 2000-2099: conflict
    CONFLICT = 2000
    ADMIN_EMAIL_TAKEN = 2001
    CUSTOMER_PHONE_TAKEN = 2002
    CATEGORY_SLUG_TAKEN = 2003
    PLANT_SLUG_TAKEN = 2004
    PLANT_SKU_TAKEN = 2005
    INSUFFICIENT_STOCK = 2006
    PLANT_UNAVAILABLE = 2007
    DUPLICATE_RESOURCE = 2008

    # 3000-3099: authentication / authorization
    UNAUTHORIZED = 3000
    INVALID_CREDENTIALS = 3001
    INVALID_TOKEN = 3002
    FORBIDDEN = 3050
    SUBMISSION_REJECTED = 3051

    # 4000-4099: bad request / business rules
    BAD_REQUEST = 4000
    VALIDATION_ERROR = 4001
    SELF_DEACTIVATION = 4002
    CUSTOMER_INACTIVE = 4003
    ORDER_TOTAL_TOO_LARGE = 4004
    INVALID_STATUS_TRANSITION = 4005
    METHOD_NOT_ALLOWED = 4006

    # 5000-5099: server side
    INTERNAL_ERROR = 5000
    DATABASE_ERROR = 5001
    SERVICE_UNAVAILABLE = 5002
    RATE_LIMITED = 5003


class AppException(Exception):
    """Base class for errors that map to a JSON error response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        error: Any = None,
        headers: dict[str, str] | None = None,
        log_detail: str | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.error = error
        self.headers = headers
        self.log_detail = log_detail
        super().__init__(self.message)


class BadRequestError(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = ErrorCode.BAD_REQUEST
    message = "Bad request"


class UnauthorizedError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = ErrorCode.UNAUTHORIZED
    message = "Could not validate credentials"


class ForbiddenError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = ErrorCode.FORBIDDEN
    message = "Forbidden"


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = ErrorCode.NOT_FOUND
    message = "Resource not found"


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = ErrorCode.CONFLICT
    message = "Conflict"


class RequestValidationAppError(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = ErrorCode.VALIDATION_ERROR
    message = "Validation error"


class RateLimitedError(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = ErrorCode.RATE_LIMITED
    message = "Too many requests"


class DatabaseError(AppException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = ErrorCode.DATABASE_ERROR
    message = "Database error"


class ServiceUnavailableError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.SERVICE_UNAVAILABLE
    message = "Service unavailable"
