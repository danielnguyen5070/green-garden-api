"""Centralized error handling: response shape, logging and no internal leaks."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Iterator

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import ErrorCode
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.features.plants.service import PlantNotFoundError
from app.main import app
from app.shared.bot_protection.service import (
    BotSignalRejectedError,
    CheckoutRateLimitedError,
)

PREFIX = "/__error-tests"
SECRET = "secret-sql SELECT * FROM admins"

router = APIRouter(prefix=PREFIX)


class _Payload(BaseModel):
    password: str
    count: int


@router.get("/app-exception")
async def _raise_app_exception() -> None:
    raise PlantNotFoundError("Plant not found")


@router.get("/http-exception")
async def _raise_http_exception() -> None:
    raise HTTPException(status_code=418, detail="I'm a teapot", headers={"X-Extra": "1"})


@router.post("/validate")
async def _validate(payload: _Payload) -> dict[str, int]:
    return {"count": payload.count}


@router.get("/unexpected")
async def _raise_unexpected() -> None:
    raise RuntimeError(SECRET)


@router.get("/integrity")
async def _raise_integrity() -> None:
    raise IntegrityError(
        "INSERT INTO customers ...",
        {},
        Exception('duplicate key value violates unique constraint "customers_phone_key"'),
    )


@router.get("/database")
async def _raise_database() -> None:
    raise OperationalError("SELECT 1", {}, Exception(SECRET))


@router.get("/bot")
async def _raise_bot() -> None:
    raise BotSignalRejectedError("Honeypot field was filled")


@router.get("/rate-limited")
async def _raise_rate_limited() -> None:
    raise CheckoutRateLimitedError(retry_after=42)


@pytest.fixture(scope="module", autouse=True)
def _mount_test_routes() -> Iterator[None]:
    before = list(app.router.routes)
    app.include_router(router)
    yield
    app.router.routes[:] = before


@pytest.fixture
async def http() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _assert_error_body(body: dict, *, status_code: int, error_code: ErrorCode) -> None:
    assert set(body) == {"status_code", "error_code", "message", "error"}
    assert body["status_code"] == status_code
    assert body["error_code"] == int(error_code)


async def test_app_exception_returns_standard_body(http: AsyncClient) -> None:
    response = await http.get(f"{PREFIX}/app-exception")
    assert response.status_code == 404
    assert response.json() == {
        "status_code": 404,
        "error_code": int(ErrorCode.PLANT_NOT_FOUND),
        "message": "Plant not found",
        "error": None,
    }
    assert response.headers[REQUEST_ID_HEADER]


async def test_request_id_is_echoed_when_safe(http: AsyncClient) -> None:
    echoed = await http.get(f"{PREFIX}/app-exception", headers={REQUEST_ID_HEADER: "abc-123"})
    assert echoed.headers[REQUEST_ID_HEADER] == "abc-123"

    replaced = await http.get(
        f"{PREFIX}/app-exception", headers={REQUEST_ID_HEADER: "bad id\nwith newline"}
    )
    assert replaced.headers[REQUEST_ID_HEADER] != "bad id\nwith newline"


async def test_http_exception_keeps_message_and_headers(http: AsyncClient) -> None:
    response = await http.get(f"{PREFIX}/http-exception")
    assert response.status_code == 418
    body = response.json()
    _assert_error_body(body, status_code=418, error_code=ErrorCode.BAD_REQUEST)
    assert body["message"] == "I'm a teapot"
    assert response.headers["X-Extra"] == "1"


async def test_unknown_route_and_wrong_method_use_standard_body(http: AsyncClient) -> None:
    missing = await http.get("/does-not-exist")
    assert missing.status_code == 404
    _assert_error_body(missing.json(), status_code=404, error_code=ErrorCode.NOT_FOUND)

    wrong_method = await http.post("/health")
    assert wrong_method.status_code == 405
    _assert_error_body(
        wrong_method.json(), status_code=405, error_code=ErrorCode.METHOD_NOT_ALLOWED
    )


async def test_validation_error_lists_fields_without_echoing_input(
    http: AsyncClient,
) -> None:
    password = "SuperSecretPassw0rd"
    response = await http.post(
        f"{PREFIX}/validate", json={"password": password, "count": "not-a-number"}
    )
    assert response.status_code == 422
    body = response.json()
    _assert_error_body(body, status_code=422, error_code=ErrorCode.VALIDATION_ERROR)
    assert body["message"] == "Validation error"
    assert [e["field"] for e in body["error"]] == ["body.count"]
    assert set(body["error"][0]) == {"field", "message", "type"}
    assert password not in response.text
    assert "not-a-number" not in response.text


async def test_unexpected_exception_is_generic_logged_and_cors_safe(
    http: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    origin = get_settings().cors_origin_list()[0]
    with caplog.at_level(logging.ERROR, logger="app.errors"):
        response = await http.get(f"{PREFIX}/unexpected", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status_code": 500,
        "error_code": int(ErrorCode.INTERNAL_ERROR),
        "message": "Internal server error",
        "error": None,
    }
    assert "secret" not in response.text
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers[REQUEST_ID_HEADER]

    logged = [r for r in caplog.records if r.exc_info and f"{PREFIX}/unexpected" in r.getMessage()]
    assert logged, "unexpected exceptions must be logged with a traceback"


async def test_debug_mode_still_returns_json_not_a_traceback() -> None:
    debug_app = FastAPI(debug=True)
    debug_app.add_middleware(RequestContextMiddleware)
    debug_app.add_middleware(CORSMiddleware, allow_origins=["*"])
    register_exception_handlers(debug_app)
    debug_app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=debug_app), base_url="http://test"
    ) as ac:
        response = await ac.get(f"{PREFIX}/unexpected")

    assert response.status_code == 500
    assert response.json()["error_code"] == int(ErrorCode.INTERNAL_ERROR)
    assert "Traceback" not in response.text
    assert "secret" not in response.text


async def test_integrity_error_is_conflict_without_constraint_name(
    http: AsyncClient,
) -> None:
    response = await http.get(f"{PREFIX}/integrity")
    assert response.status_code == 409
    body = response.json()
    _assert_error_body(body, status_code=409, error_code=ErrorCode.DUPLICATE_RESOURCE)
    assert "customers_phone_key" not in response.text
    assert "INSERT" not in response.text


async def test_other_database_errors_are_generic_500(http: AsyncClient) -> None:
    response = await http.get(f"{PREFIX}/database")
    assert response.status_code == 500
    body = response.json()
    _assert_error_body(body, status_code=500, error_code=ErrorCode.DATABASE_ERROR)
    assert body["message"] == "Database error"
    assert "secret" not in response.text


async def test_bot_rejection_hides_the_reason(http: AsyncClient) -> None:
    response = await http.get(f"{PREFIX}/bot")
    assert response.status_code == 403
    body = response.json()
    _assert_error_body(body, status_code=403, error_code=ErrorCode.SUBMISSION_REJECTED)
    assert body["message"] == "Submission rejected"
    assert "Honeypot" not in response.text


async def test_rate_limit_sets_retry_after(http: AsyncClient) -> None:
    response = await http.get(f"{PREFIX}/rate-limited")
    assert response.status_code == 429
    _assert_error_body(response.json(), status_code=429, error_code=ErrorCode.RATE_LIMITED)
    assert response.headers["Retry-After"] == "42"


async def test_missing_auth_cookie_returns_401_standard_body(http: AsyncClient) -> None:
    response = await http.get("/api/v1/admins")
    assert response.status_code == 401
    body = response.json()
    _assert_error_body(body, status_code=401, error_code=ErrorCode.INVALID_TOKEN)
    assert body["message"] == "Could not validate credentials"
