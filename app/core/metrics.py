"""Prometheus metrics: definitions, HTTP middleware and the protected `/metrics` route.

Uvicorn runs several workers in production, so metrics use prometheus_client's
multiprocess mode whenever `PROMETHEUS_MULTIPROC_DIR` is set. That directory
must be emptied before the workers start (see `scripts/start.sh`).

Labels are kept low-cardinality: routes are recorded by template
(`/api/v1/plants/{plant_id}`), never by raw path.
"""

from __future__ import annotations

import atexit
import os
import secrets
import time

from fastapi import APIRouter, Header, HTTPException, Response, status
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from sqlalchemy import event
from sqlalchemy.pool import Pool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

METRICS_PATH = "/metrics"
UNMATCHED_ROUTE = "__unmatched__"

_EXCLUDED_PATHS = frozenset({METRICS_PATH, "/health"})
_KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests by method, route template and status code.",
    ["method", "route", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds (streaming responses excluded).",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being processed.",
    ["method"],
    multiprocess_mode="livesum",
)

APP_EXCEPTIONS_TOTAL = Counter(
    "app_exceptions_total",
    "Exceptions handled by the global exception handlers.",
    ["exception_type", "handler"],
)

DB_POOL_CHECKED_OUT = Gauge(
    "db_pool_checked_out_connections",
    "Database connections currently checked out of the pool.",
    multiprocess_mode="livesum",
)

DB_POOL_OPEN = Gauge(
    "db_pool_open_connections",
    "Database connections currently open (idle or checked out).",
    multiprocess_mode="livesum",
)

DB_POOL_MAX = Gauge(
    "db_pool_max_connections",
    "Maximum database connections allowed (pool_size + max_overflow).",
    multiprocess_mode="livesum",
)


def _multiprocess_enabled() -> bool:
    return bool(os.environ.get("PROMETHEUS_MULTIPROC_DIR"))


def render_metrics() -> bytes:
    if _multiprocess_enabled():
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest(REGISTRY)


def mark_worker_dead() -> None:
    """Drop this worker's live gauges; call on worker shutdown."""
    if _multiprocess_enabled():
        multiprocess.mark_process_dead(os.getpid())


# One-off processes (CLI, scripts) that import the app must not leave live gauges
# behind. Uvicorn workers exit via os._exit, so they rely on the lifespan hook instead.
atexit.register(mark_worker_dead)


def record_exception(exception_type: str, handler: str) -> None:
    APP_EXCEPTIONS_TOTAL.labels(exception_type=exception_type, handler=handler).inc()


def instrument_pool(pool: Pool, max_connections: int) -> None:
    DB_POOL_MAX.set(max_connections)

    @event.listens_for(pool, "connect")
    def _on_connect(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        DB_POOL_OPEN.inc()

    @event.listens_for(pool, "close")
    def _on_close(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        DB_POOL_OPEN.dec()

    @event.listens_for(pool, "close_detached")
    def _on_close_detached(dbapi_connection) -> None:  # type: ignore[no-untyped-def]
        DB_POOL_OPEN.dec()

    @event.listens_for(pool, "checkout")
    def _on_checkout(dbapi_connection, connection_record, connection_proxy) -> None:  # type: ignore[no-untyped-def]
        DB_POOL_CHECKED_OUT.inc()

    @event.listens_for(pool, "checkin")
    def _on_checkin(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        DB_POOL_CHECKED_OUT.dec()


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    return template or UNMATCHED_ROUTE


class PrometheusMiddleware:
    """
    Record request count, latency and in-flight requests.

    Pure ASGI so streaming responses are not buffered. Must sit outside
    `RequestContextMiddleware` so it sees the final status of unhandled errors.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return

        method = scope["method"] if scope["method"] in _KNOWN_METHODS else "OTHER"
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        streaming = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, streaming
            if message["type"] == "http.response.start":
                status_code = message["status"]
                for name, value in message.get("headers", []):
                    if name.lower() == b"content-type" and value.startswith(b"text/event-stream"):
                        streaming = True
            await send(message)

        in_progress = HTTP_REQUESTS_IN_PROGRESS.labels(method=method)
        in_progress.inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            in_progress.dec()
            route = _route_template(scope)
            HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=str(status_code)).inc()
            # SSE streams stay open for the whole conversation and would skew P95/P99.
            if not streaming:
                HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(duration)


router = APIRouter()


@router.get(METRICS_PATH, include_in_schema=False)
async def metrics(authorization: str | None = Header(default=None)) -> Response:
    token = get_settings().metrics_token
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not authorization or not secrets.compare_digest(
        authorization.encode(), f"Bearer {token}".encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)
