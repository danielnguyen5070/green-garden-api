"""Unit tests for the storefront cache-revalidation webhook client."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app.core.config import Settings
from app.shared import storefront_notify
from app.shared.storefront_notify import (
    build_request,
    notify_storefront,
    send_storefront_notification,
    sign_payload,
)

SECRET = "test-revalidate-secret"
URL = "http://storefront.test/api/revalidate"


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "jwt_secret_key": "test-secret",
        "storefront_revalidate_url": URL,
        "storefront_revalidate_secret": SECRET,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storefront_notify, "get_settings", lambda: _settings())


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(storefront_notify.httpx, "AsyncClient", factory)


def test_signature_matches_webhook_format() -> None:
    expected = hmac.new(
        SECRET.encode(), b"1700000000.{\"entity\":\"plants\"}", hashlib.sha256
    ).hexdigest()
    assert sign_payload(SECRET, "1700000000", '{"entity":"plants"}') == expected


def test_build_request_signs_body_and_dedupes_slugs() -> None:
    body, headers = build_request(
        SECRET, "plants", ["monstera", None, "monstera", "old-monstera"], now=1700000000
    )

    assert json.loads(body) == {"entity": "plants", "slugs": ["monstera", "old-monstera"]}
    assert headers["X-Revalidate-Timestamp"] == "1700000000"
    assert headers["X-Revalidate-Signature"] == sign_payload(SECRET, "1700000000", body)


def test_build_request_omits_empty_slugs() -> None:
    body, _ = build_request(SECRET, "categories", [], now=1700000000)
    assert json.loads(body) == {"entity": "categories"}


async def test_send_posts_signed_payload(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"revalidated": ["plants"]})

    _mock_client(monkeypatch, handler)
    await send_storefront_notification("plants", ["monstera"])

    assert len(received) == 1
    request = received[0]
    assert str(request.url) == URL
    timestamp = request.headers["X-Revalidate-Timestamp"]
    assert request.headers["X-Revalidate-Signature"] == sign_payload(
        SECRET, timestamp, request.content.decode()
    )


async def test_send_swallows_network_errors(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("storefront down", request=request)

    _mock_client(monkeypatch, handler)
    await send_storefront_notification("plants", ["monstera"])


async def test_send_swallows_error_responses(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_client(monkeypatch, lambda request: httpx.Response(401))
    await send_storefront_notification("reviews")


async def test_send_is_noop_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        storefront_notify,
        "get_settings",
        lambda: _settings(storefront_revalidate_url=None),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not send when unconfigured")

    _mock_client(monkeypatch, handler)
    await send_storefront_notification("plants")


async def test_notify_schedules_task_that_survives_failure(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("storefront down", request=request)

    _mock_client(monkeypatch, handler)
    notify_storefront("plants", ["monstera"])

    tasks = list(storefront_notify._pending_tasks)
    assert len(tasks) == 1
    await asyncio.gather(*tasks)
    assert tasks[0].exception() is None


def test_notify_without_event_loop_does_not_raise(configured: None) -> None:
    notify_storefront("plants", ["monstera"])
