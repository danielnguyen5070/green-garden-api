"""Security response headers for a JSON API that also serves Swagger UI and ReDoc."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Nothing an API response renders may load resources or be framed.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

# FastAPI's default /docs and /redoc pages: CDN bundles, an inline init script,
# Google Fonts, data: images and a blob: search worker (ReDoc).
DOCS_CSP = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)

DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})

# HSTS is set by the TLS terminator (Nginx/Cloudflare): the app only sees plain HTTP.
BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Browser fetches from the storefront are CORS requests, which CORP ignores.
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    """
    Add security headers to every HTTP response without overriding values a
    route set itself.

    Pure ASGI (not `BaseHTTPMiddleware`) so streaming responses are untouched.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"].removeprefix(scope.get("root_path", ""))
        csp = DOCS_CSP if path in DOCS_PATHS else API_CSP

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in BASE_HEADERS.items():
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", csp)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
