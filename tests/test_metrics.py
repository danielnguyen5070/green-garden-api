"""Prometheus instrumentation: /metrics protection and low-cardinality labels."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Iterator

import pytest
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from app.core.config import get_settings
from app.core.metrics import UNMATCHED_ROUTE
from app.main import app

PREFIX = "/__metrics-tests"
TOKEN = "test-metrics-token"

router = APIRouter(prefix=PREFIX)


@router.get("/items/{item_id}")
async def _item(item_id: int) -> dict[str, int]:
    return {"id": item_id}


@router.get("/boom")
async def _boom() -> None:
    raise RuntimeError("boom")


@router.get("/stream")
async def _stream() -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        yield "data: hi\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@pytest.fixture(scope="module", autouse=True)
def _mount_test_routes() -> Iterator[None]:
    before = list(app.router.routes)
    app.include_router(router)
    yield
    app.router.routes[:] = before


@pytest.fixture
def metrics_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("METRICS_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield TOKEN
    get_settings.cache_clear()


@pytest.fixture
async def http() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _requests(route: str, status: str, method: str = "GET") -> float:
    value = REGISTRY.get_sample_value(
        "http_requests_total", {"method": method, "route": route, "status": status}
    )
    return value or 0.0


def _latency_count(route: str, method: str = "GET") -> float:
    value = REGISTRY.get_sample_value(
        "http_request_duration_seconds_count", {"method": method, "route": route}
    )
    return value or 0.0


def _exceptions(exception_type: str, handler: str) -> float:
    value = REGISTRY.get_sample_value(
        "app_exceptions_total", {"exception_type": exception_type, "handler": handler}
    )
    return value or 0.0


async def test_metrics_disabled_without_token(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "")
    get_settings.cache_clear()
    try:
        response = await http.get("/metrics")
    finally:
        get_settings.cache_clear()
    assert response.status_code == 404


async def test_metrics_requires_bearer_token(http: AsyncClient, metrics_token: str) -> None:
    missing = await http.get("/metrics")
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"

    wrong = await http.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401

    ok = await http.get("/metrics", headers={"Authorization": f"Bearer {metrics_token}"})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in ok.text


async def test_metrics_endpoint_is_hidden_from_openapi(http: AsyncClient) -> None:
    schema = (await http.get("/openapi.json")).json()
    assert "/metrics" not in schema["paths"]


async def test_requests_are_labelled_by_route_template(http: AsyncClient) -> None:
    template = f"{PREFIX}/items/{{item_id}}"
    before = _requests(template, "200")

    await http.get(f"{PREFIX}/items/1")
    await http.get(f"{PREFIX}/items/2")

    assert _requests(template, "200") == before + 2
    assert REGISTRY.get_sample_value(
        "http_requests_total", {"method": "GET", "route": f"{PREFIX}/items/1", "status": "200"}
    ) is None


async def test_unknown_paths_share_one_label(http: AsyncClient) -> None:
    before = _requests(UNMATCHED_ROUTE, "404")
    await http.get("/random-scanner-path-1")
    await http.get("/random-scanner-path-2")
    assert _requests(UNMATCHED_ROUTE, "404") == before + 2


async def test_unhandled_exception_is_counted_as_500(http: AsyncClient) -> None:
    route = f"{PREFIX}/boom"
    requests_before = _requests(route, "500")
    exceptions_before = _exceptions("RuntimeError", "unhandled")

    response = await http.get(route)

    assert response.status_code == 500
    assert _requests(route, "500") == requests_before + 1
    assert _exceptions("RuntimeError", "unhandled") == exceptions_before + 1


async def test_streaming_responses_skip_latency_histogram(http: AsyncClient) -> None:
    route = f"{PREFIX}/stream"
    latency_before = _latency_count(route)
    requests_before = _requests(route, "200")

    await http.get(route)

    assert _requests(route, "200") == requests_before + 1
    assert _latency_count(route) == latency_before


async def test_health_and_metrics_are_not_recorded(
    http: AsyncClient, metrics_token: str
) -> None:
    await http.get("/health")
    await http.get("/metrics", headers={"Authorization": f"Bearer {metrics_token}"})
    for route in ("/health", "/metrics"):
        assert _requests(route, "200") == 0


async def test_in_progress_gauge_returns_to_zero(http: AsyncClient) -> None:
    await http.get(f"{PREFIX}/items/3")
    assert REGISTRY.get_sample_value("http_requests_in_progress", {"method": "GET"}) == 0
