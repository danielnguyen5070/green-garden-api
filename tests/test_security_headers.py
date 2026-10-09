"""Security response headers on JSON, streaming, error and docs responses."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, AsyncIterator
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient
from httpx import Response as HttpxResponse

from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.request_context import RequestContextMiddleware
from app.core.security_headers import API_CSP, DOCS_CSP, SecurityHeadersMiddleware
from app.main import app

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-resource-policy": "same-origin",
}

# Owned by the TLS terminator, or deliberately not sent by the API.
NOT_SENT = (
    "strict-transport-security",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
)


@pytest.fixture
async def http() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _assert_api_headers(response: HttpxResponse, csp: str = API_CSP) -> None:
    for name, value in EXPECTED.items():
        assert response.headers.get_list(name) == [value], name
    assert response.headers.get_list("content-security-policy") == [csp]
    for name in NOT_SENT:
        assert name not in response.headers, name


def _csp_sources(csp: str, directive: str) -> list[str]:
    for part in csp.split(";"):
        name, *sources = part.split()
        if name == directive:
            return sources
    return []


async def test_json_response_has_strict_headers(http: AsyncClient) -> None:
    response = await http.get("/health")
    assert response.status_code == 200
    _assert_api_headers(response)


async def test_openapi_schema_uses_api_csp(http: AsyncClient) -> None:
    response = await http.get("/openapi.json")
    assert response.status_code == 200
    _assert_api_headers(response)


async def test_error_response_has_headers(http: AsyncClient) -> None:
    response = await http.get("/does-not-exist")
    assert response.status_code == 404
    _assert_api_headers(response)


async def test_cors_preflight_has_headers_and_still_allows_origin(http: AsyncClient) -> None:
    origin = get_settings().cors_origin_list()[0]
    response = await http.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    _assert_api_headers(response)


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/docs/oauth2-redirect"])
async def test_docs_pages_use_docs_csp(http: AsyncClient, path: str) -> None:
    response = await http.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    _assert_api_headers(response, csp=DOCS_CSP)


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
async def test_docs_csp_allows_every_external_asset(http: AsyncClient, path: str) -> None:
    html = (await http.get(path)).text
    # Stylesheets and the favicon are both <link> tags.
    allowed_by_tag = {
        ("script", "src"): _csp_sources(DOCS_CSP, "script-src"),
        ("link", "href"): _csp_sources(DOCS_CSP, "style-src") + _csp_sources(DOCS_CSP, "img-src"),
    }
    checked = 0
    for (tag, attr), allowed in allowed_by_tag.items():
        for match in re.finditer(rf'<{tag}[^>]*\b{attr}="([^"]+)"', html):
            url = urlparse(match.group(1))
            if url.netloc:
                assert f"{url.scheme}://{url.netloc}" in allowed, f"{url.geturl()} blocked"
                checked += 1
    assert checked, f"no external assets found on {path}"


async def test_streaming_response_keeps_headers_and_body() -> None:
    stream_app = FastAPI()
    stream_app.add_middleware(SecurityHeadersMiddleware)

    async def _chunks() -> AsyncIterator[bytes]:
        yield b"data: one\n\n"
        yield b"data: two\n\n"

    @stream_app.get("/stream")
    async def _stream() -> StreamingResponse:
        return StreamingResponse(_chunks(), media_type="text/event-stream")

    async with AsyncClient(transport=ASGITransport(app=stream_app), base_url="http://t") as ac:
        response = await ac.get("/stream")

    assert response.text == "data: one\n\ndata: two\n\n"
    _assert_api_headers(response)


async def test_route_values_are_not_overridden_or_duplicated() -> None:
    custom_app = FastAPI()
    custom_app.add_middleware(SecurityHeadersMiddleware)

    @custom_app.get("/custom")
    async def _custom() -> Response:
        return Response(headers={"X-Frame-Options": "SAMEORIGIN"})

    async with AsyncClient(transport=ASGITransport(app=custom_app), base_url="http://t") as ac:
        response = await ac.get("/custom")

    assert response.headers.get_list("x-frame-options") == ["SAMEORIGIN"]
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_unhandled_exception_500_has_headers() -> None:
    crash_app = FastAPI()
    crash_app.add_middleware(RequestContextMiddleware)
    crash_app.add_middleware(SecurityHeadersMiddleware)
    register_exception_handlers(crash_app)

    @crash_app.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("boom")

    async with AsyncClient(transport=ASGITransport(app=crash_app), base_url="http://t") as ac:
        response = await ac.get("/boom")

    assert response.status_code == 500
    _assert_api_headers(response)
