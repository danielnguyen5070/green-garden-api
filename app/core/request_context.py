"""Per-request context: request id propagation and the last-resort 500 guard."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Accept a caller-supplied id only when it is short and log-safe.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def get_request_id() -> str | None:
    return request_id_ctx.get()


class RequestContextMiddleware:
    """
    Assign a request id, echo it in `X-Request-ID`, and turn unexpected
    exceptions into the standard JSON 500.

    Pure ASGI (not `BaseHTTPMiddleware`) so streaming responses are untouched.
    It must sit inside `CORSMiddleware` so 500 responses still carry CORS
    headers, which Starlette's outermost `ServerErrorMiddleware` cannot do.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Request(scope).headers.get(REQUEST_ID_HEADER)
        request_id = (
            incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        )
        token = request_id_ctx.set(request_id)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            if response_started:
                raise
            from app.core.error_handlers import unhandled_exception_handler

            response = await unhandled_exception_handler(Request(scope), exc)
            await response(scope, receive, send_with_request_id)
        finally:
            request_id_ctx.reset(token)
