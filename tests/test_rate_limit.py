"""Rate limiting: client IP resolution, route limits, 429 shape, exemptions, fail-open."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from starlette.requests import Request

from app.core.config import get_settings
from app.core.exceptions import ErrorCode
from app.core.rate_limit import client_ip, limiter
from app.core.request_context import REQUEST_ID_HEADER
from app.features.admins.models import Admin
from app.features.chat.deepseek import DeepSeekService

LOGIN = "/api/v1/auth/login"
CHAT_STREAM = "/api/v1/chat/stream"
QUOTE = "/api/v1/storefront/orders/quote"
CATEGORIES = "/api/v1/storefront/categories"
SEPAY_WEBHOOK = "/api/v1/payments/sepay/webhook"


def _from(ip: str) -> dict[str, str]:
    """Headers as set by the trusted Nginx for a client at `ip`."""
    return {"X-Forwarded-For": ip}


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def _assert_rate_limited(response) -> None:
    assert response.status_code == 429
    body = response.json()
    assert body["status_code"] == 429
    assert body["error_code"] == ErrorCode.RATE_LIMITED
    assert body["message"]
    assert int(response.headers["Retry-After"]) >= 0


async def _bad_login(client: AsyncClient, email: str, ip: str):
    return await client.post(
        LOGIN, json={"email": email, "password": "wrong-password"}, headers=_from(ip)
    )


# --- client IP resolution ---------------------------------------------------


@pytest.fixture
def trusted(rate_limiting):
    rate_limiting(trusted_proxies="127.0.0.1,::1,172.16.0.0/12")


def test_untrusted_peer_ignores_forwarded_header(trusted) -> None:
    assert client_ip(_request("203.0.113.7", "198.51.100.1")) == "203.0.113.7"


def test_trusted_peer_uses_forwarded_client(trusted) -> None:
    assert client_ip(_request("172.18.0.1", "198.51.100.1")) == "198.51.100.1"


def test_rightmost_untrusted_address_wins(trusted) -> None:
    # A client-supplied entry to the left of the real client is ignored.
    request = _request("172.18.0.1", "1.2.3.4, 198.51.100.1, 127.0.0.1")
    assert client_ip(request) == "198.51.100.1"


def test_malformed_forwarded_entry_falls_back_to_peer(trusted) -> None:
    assert client_ip(_request("172.18.0.1", "not-an-ip")) == "172.18.0.1"
    assert client_ip(_request("172.18.0.1", "")) == "172.18.0.1"


def test_ipv6_forwarded_client(trusted) -> None:
    assert client_ip(_request("::1", "2001:db8::1")) == "2001:db8::1"


def test_missing_forwarded_header_uses_peer(trusted) -> None:
    assert client_ip(_request("127.0.0.1")) == "127.0.0.1"


# --- login ------------------------------------------------------------------


async def test_login_ip_limit_returns_standard_429(client: AsyncClient, rate_limiting) -> None:
    rate_limiting(rate_limit_login="2/minute", rate_limit_login_email_failures="100/hour")
    origin = get_settings().cors_origin_list()[0]
    email = f"nobody-{uuid4()}@example.com"

    for _ in range(2):
        assert (await _bad_login(client, email, "198.51.100.10")).status_code == 401

    response = await client.post(
        LOGIN,
        json={"email": email, "password": "wrong-password"},
        headers={**_from("198.51.100.10"), "Origin": origin},
    )
    _assert_rate_limited(response)
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers[REQUEST_ID_HEADER]
    assert response.headers["access-control-allow-origin"] == origin


async def test_login_ip_counters_are_per_client(client: AsyncClient, rate_limiting) -> None:
    rate_limiting(rate_limit_login="1/minute", rate_limit_login_email_failures="100/hour")
    email = f"nobody-{uuid4()}@example.com"

    assert (await _bad_login(client, email, "198.51.100.20")).status_code == 401
    assert (await _bad_login(client, email, "198.51.100.20")).status_code == 429
    assert (await _bad_login(client, email, "198.51.100.21")).status_code == 401


async def test_untrusted_peer_cannot_spoof_forwarded_for(
    client: AsyncClient, rate_limiting
) -> None:
    from app.main import app

    rate_limiting(rate_limit_login="1/minute", rate_limit_login_email_failures="100/hour")
    email = f"nobody-{uuid4()}@example.com"
    transport = ASGITransport(app=app, client=("203.0.113.50", 4321))
    async with AsyncClient(transport=transport, base_url="http://test") as direct:
        assert (await _bad_login(direct, email, "198.51.100.30")).status_code == 401
        assert (await _bad_login(direct, email, "198.51.100.31")).status_code == 429


async def test_login_email_failures_limited_across_ips(
    client: AsyncClient, rate_limiting, active_admin: Admin
) -> None:
    rate_limiting(rate_limit_login="100/minute", rate_limit_login_email_failures="2/hour")

    assert (await _bad_login(client, active_admin.email, "198.51.100.40")).status_code == 401
    assert (await _bad_login(client, active_admin.email, "198.51.100.41")).status_code == 401

    # Even the correct password is refused until the window passes.
    response = await client.post(
        LOGIN,
        json={"email": active_admin.email, "password": "correct-password"},
        headers=_from("198.51.100.42"),
    )
    _assert_rate_limited(response)


async def test_successful_logins_do_not_count_as_failures(
    client: AsyncClient, rate_limiting, active_admin: Admin
) -> None:
    rate_limiting(rate_limit_login="100/minute", rate_limit_login_email_failures="2/hour")
    good = {"email": active_admin.email, "password": "correct-password"}

    assert (await _bad_login(client, active_admin.email, "198.51.100.50")).status_code == 401
    for _ in range(3):
        response = await client.post(LOGIN, json=good, headers=_from("198.51.100.50"))
        assert response.status_code == 200
    assert (await _bad_login(client, active_admin.email, "198.51.100.50")).status_code == 401
    assert (await _bad_login(client, active_admin.email, "198.51.100.50")).status_code == 429


# --- chat (AI) ----------------------------------------------------------------


@pytest.fixture
def chat_unconfigured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(DeepSeekService, "is_configured", property(lambda self: False))


async def test_chat_limit_returns_json_429_before_streaming(
    client: AsyncClient, rate_limiting, chat_unconfigured
) -> None:
    rate_limiting(rate_limit_chat="2/minute")

    for _ in range(2):
        response = await client.post(
            CHAT_STREAM, json={"message": "hi"}, headers=_from("198.51.100.60")
        )
        assert response.status_code == 503

    response = await client.post(
        CHAT_STREAM, json={"message": "hi"}, headers=_from("198.51.100.60")
    )
    _assert_rate_limited(response)
    assert response.headers["content-type"].startswith("application/json")


async def test_chat_global_limit_is_shared_by_all_clients(
    client: AsyncClient, rate_limiting, chat_unconfigured
) -> None:
    rate_limiting(rate_limit_chat="100/minute", rate_limit_chat_global="2/minute")

    for ip in ("198.51.100.70", "198.51.100.71"):
        response = await client.post(CHAT_STREAM, json={"message": "hi"}, headers=_from(ip))
        assert response.status_code == 503

    response = await client.post(
        CHAT_STREAM, json={"message": "hi"}, headers=_from("198.51.100.72")
    )
    _assert_rate_limited(response)


async def test_chat_stream_chunks_survive_rate_limit_middleware(
    client: AsyncClient, rate_limiting, monkeypatch: pytest.MonkeyPatch
) -> None:
    rate_limiting(rate_limit_chat="10/minute")

    async def fake_stream(self, **_: object) -> AsyncIterator[str]:
        for chunk in ("Xin ", "chào", "!"):
            yield chunk

    monkeypatch.setattr(DeepSeekService, "is_configured", property(lambda self: True))
    monkeypatch.setattr(DeepSeekService, "stream_chat", fake_stream)

    response = await client.post(
        CHAT_STREAM, json={"message": "hi"}, headers=_from("198.51.100.80")
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-RateLimit-Limit"]
    assert "chào" in response.text


# --- public writes and global default -----------------------------------------


async def test_quote_limit(client: AsyncClient, rate_limiting) -> None:
    rate_limiting(rate_limit_quote="2/minute")
    body = {"items": [{"plant_id": str(uuid4()), "quantity": 1}]}

    for _ in range(2):
        response = await client.post(QUOTE, json=body, headers=_from("198.51.100.90"))
        assert response.status_code == 200
    _assert_rate_limited(await client.post(QUOTE, json=body, headers=_from("198.51.100.90")))


async def test_global_default_applies_to_public_get(client: AsyncClient, rate_limiting) -> None:
    rate_limiting(rate_limit_default="2/minute")

    for _ in range(2):
        response = await client.get(CATEGORIES, headers=_from("198.51.100.100"))
        assert response.status_code == 200
        assert response.headers["X-RateLimit-Limit"] == "2"
    _assert_rate_limited(await client.get(CATEGORIES, headers=_from("198.51.100.100")))


async def test_exempt_routes_are_never_limited(client: AsyncClient, rate_limiting) -> None:
    rate_limiting(rate_limit_default="1/minute")
    headers = _from("198.51.100.110")

    for _ in range(3):
        assert (await client.get("/health", headers=headers)).status_code == 200
        assert (await client.get("/metrics", headers=headers)).status_code != 429
        response = await client.post(SEPAY_WEBHOOK, json={}, headers=headers)
        assert response.status_code != 429


async def test_disabled_limiter_never_limits(client: AsyncClient, rate_limiting) -> None:
    rate_limiting(rate_limit_default="1/minute")
    limiter.enabled = False

    for _ in range(3):
        assert (await client.get(CATEGORIES, headers=_from("198.51.100.120"))).status_code == 200


# --- storage failures ---------------------------------------------------------


async def test_unreachable_storage_fails_open_to_memory(
    client: AsyncClient, rate_limiting, monkeypatch: pytest.MonkeyPatch
) -> None:
    rate_limiting(rate_limit_default="2/minute")
    dead = storage_from_string("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    monkeypatch.setattr(limiter, "_storage", dead)
    monkeypatch.setattr(limiter, "_limiter", MovingWindowRateLimiter(dead))

    for _ in range(2):
        response = await client.get(CATEGORIES, headers=_from("198.51.100.130"))
        assert response.status_code == 200
    # The in-memory fallback keeps enforcing limits while Redis is down.
    _assert_rate_limited(await client.get(CATEGORIES, headers=_from("198.51.100.130")))


@pytest.mark.redis
def test_redis_counters_are_shared_between_workers() -> None:
    uri = os.environ.get("RATE_LIMIT_TEST_REDIS_URI")
    if not uri:
        pytest.skip("RATE_LIMIT_TEST_REDIS_URI is not set")

    def worker() -> Limiter:
        return Limiter(key_func=lambda: "unused", storage_uri=uri, strategy="moving-window")

    first, second = worker(), worker()
    item = parse("2/minute")
    key = ("gg-rl-test", f"shared-{uuid4()}")

    assert first.limiter.hit(item, *key)
    assert second.limiter.hit(item, *key)
    assert not first.limiter.hit(item, *key)
    assert not second.limiter.test(item, *key)
