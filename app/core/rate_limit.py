"""Rate limiting: SlowAPI limiter, client IP resolution and the ASGI middleware.

Limits are counted per client IP. `RateLimitMiddleware` enforces the global
`RATE_LIMIT_DEFAULT` ceiling on every non-exempt route; stricter limits are
added per route with `@rate_limit(...)`. Counters live in
`RATE_LIMIT_STORAGE_URI` (Redis in production) so all workers share them. When
the storage is unreachable the limiter fails open onto per-worker memory
counters instead of failing requests.

Limit values are callables reading settings at request time, so environment
overrides apply without re-importing the routes.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address
from typing import Any, TypeVar, get_type_hints

from fastapi import status
from limits import parse_many
from slowapi import Limiter
from slowapi.middleware import _find_route_handler, _should_exempt, async_check_limits
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.exceptions import RateLimitedError
from app.core.security import normalize_email

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

RATE_LIMITED_RESPONSES = {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "description": "Too many requests; retry after `Retry-After` seconds"
    }
}

KEY_PREFIX = "gg-rl"
_LOGIN_EMAIL_SCOPE = "login-email"
_CHAT_GLOBAL_KEY = "chat-global"


def _parse_ip(value: str) -> IPv4Address | IPv6Address | None:
    try:
        return ip_address(value.strip())
    except ValueError:
        return None


def _is_trusted(ip: IPv4Address | IPv6Address, networks: list[IPv4Network | IPv6Network]) -> bool:
    return any(ip in network for network in networks)


def client_ip(request: Request) -> str:
    """
    Return the client IP used as the rate-limit key.

    `X-Forwarded-For` is honoured only when the direct peer is a trusted proxy;
    it is then walked right to left, skipping trusted hops, and the first
    untrusted address wins. A malformed entry stops the walk, so a client can
    never inject an address past the proxy.
    """
    peer = request.client.host if request.client else ""
    peer_ip = _parse_ip(peer)
    networks = get_settings().trusted_proxy_networks()
    if peer_ip is None or not _is_trusted(peer_ip, networks):
        return peer or "unknown"

    forwarded = request.headers.get("x-forwarded-for", "")
    for entry in reversed(forwarded.split(",")):
        candidate = _parse_ip(entry)
        if candidate is None:
            break
        if not _is_trusted(candidate, networks):
            return str(candidate)
    return peer


def _settings_limit(name: str):
    def provider() -> str:
        return getattr(get_settings(), name)

    provider.__name__ = name
    return provider


default_limit = _settings_limit("rate_limit_default")
login_limit = _settings_limit("rate_limit_login")
refresh_limit = _settings_limit("rate_limit_refresh")
chat_limit = _settings_limit("rate_limit_chat")
chat_global_limit = _settings_limit("rate_limit_chat_global")
public_write_limit = _settings_limit("rate_limit_public_write")
quote_limit = _settings_limit("rate_limit_quote")


def chat_global_key() -> str:
    return _CHAT_GLOBAL_KEY


def _build_limiter() -> Limiter:
    settings = get_settings()
    return Limiter(
        key_func=client_ip,
        application_limits=[default_limit],
        storage_uri=settings.rate_limit_storage_uri,
        strategy=settings.rate_limit_strategy,
        headers_enabled=True,
        enabled=settings.rate_limit_enabled,
        swallow_errors=True,
        in_memory_fallback_enabled=True,
        key_prefix=KEY_PREFIX,
        key_style="endpoint",
    )


limiter = _build_limiter()


def rate_limit(limit_value: Callable[[], str], **kwargs: Any) -> Callable[[F], F]:
    """
    `limiter.limit` for FastAPI routes.

    SlowAPI's wrapper lives in another module, so FastAPI would resolve the
    route's string annotations (`from __future__ import annotations`) against
    the wrong globals. Resolve them on the route function first.
    """
    decorator = limiter.limit(limit_value, **kwargs)

    def apply(func: F) -> F:
        func.__annotations__ = get_type_hints(func, include_extras=True)
        return decorator(func)

    return apply


def exempt(func: F) -> F:
    """Exempt a route from every limit, leaving the function unwrapped."""
    limiter.exempt(func)
    return func


class LoginRateLimitedError(RateLimitedError):
    """Raised when an email has too many recent failed logins."""

    message = "Too many failed login attempts. Please try again later."

    def __init__(self, retry_after: int) -> None:
        super().__init__(headers={"Retry-After": str(retry_after)})
        self.retry_after = retry_after


def _login_email_identifiers(email: str) -> tuple[str, str, str]:
    # Hashed so admin emails are never stored in the rate-limit backend.
    digest = hashlib.sha256(normalize_email(email).encode()).hexdigest()
    return KEY_PREFIX, _LOGIN_EMAIL_SCOPE, digest


def ensure_login_email_allowed(email: str) -> None:
    """Raise `LoginRateLimitedError` once the email reached its failure limit."""
    if not limiter.enabled:
        return
    identifiers = _login_email_identifiers(email)
    try:
        for item in parse_many(get_settings().rate_limit_login_email_failures):
            if not limiter.limiter.test(item, *identifiers):
                reset_at, _ = limiter.limiter.get_window_stats(item, *identifiers)
                raise LoginRateLimitedError(retry_after=max(1, math.ceil(reset_at - time.time())))
    except LoginRateLimitedError:
        raise
    except Exception:  # noqa: BLE001 — storage outage must not block logins
        logger.exception("Login email rate-limit check failed; allowing request")


def record_login_email_failure(email: str) -> None:
    """Count one failed login against the email."""
    if not limiter.enabled:
        return
    identifiers = _login_email_identifiers(email)
    try:
        for item in parse_many(get_settings().rate_limit_login_email_failures):
            limiter.limiter.hit(item, *identifiers)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record login failure for rate limiting")


def reset_rate_limits() -> None:
    """Clear all counters (tests and operational resets)."""
    limiter.reset()
    if limiter._fallback_limiter is not None:
        limiter._fallback_storage.reset()
    limiter._storage_dead = False


class RateLimitMiddleware:
    """
    Enforce the global per-IP limit and add `X-RateLimit-*` headers.

    Replaces `slowapi.middleware.SlowAPIASGIMiddleware`, whose send wrapper
    re-sends `http.response.start` for every body chunk and therefore breaks
    streamed responses. Here headers are added once, on `http.response.start`.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        app = scope["app"]
        active: Limiter = app.state.limiter
        if not active.enabled:
            await self.app(scope, receive, send)
            return

        handler = _find_route_handler(app.routes, scope)
        if _should_exempt(active, handler):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive, send=send)
        error_response, inject_headers = await async_check_limits(active, request, handler, app)
        if error_response is not None:
            await error_response(scope, receive, send)
            return
        if not inject_headers:
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", []))
                active._inject_asgi_headers(
                    MutableHeaders(scope=message), request.state.view_rate_limit
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)
