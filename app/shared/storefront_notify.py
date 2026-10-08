"""Tell the Next.js storefront to drop cached catalog data after a change.

The storefront caches catalog responses for hours and relies on this webhook
(``POST {STOREFRONT_REVALIDATE_URL}``) to refresh them. The body is
``{"entity": ..., "slugs": [...]}``, signed as
``hex(HMAC-SHA256(secret, f"{timestamp}.{body}"))`` with the Unix timestamp in
``X-Revalidate-Timestamp`` and the digest in ``X-Revalidate-Signature``.

Notifications are best effort: they run as background tasks after the
database commit, failures are logged, and nothing is ever raised to the
caller. When the URL or secret is unset, notifications are disabled.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Iterable
from typing import Literal

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

StorefrontEntity = Literal["plants", "categories", "reviews", "shipping_policy"]

_TIMEOUT_SECONDS = 5.0

# Keeps fire-and-forget tasks referenced until they finish.
_pending_tasks: set[asyncio.Task[None]] = set()


def sign_payload(secret: str, timestamp: str, body: str) -> str:
    """Hex HMAC-SHA256 of ``"{timestamp}.{body}"``, as the webhook verifies it."""
    message = f"{timestamp}.{body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def build_request(
    secret: str,
    entity: StorefrontEntity,
    slugs: Iterable[str | None] = (),
    *,
    now: float | None = None,
) -> tuple[str, dict[str, str]]:
    """Serialized body and signed headers for one notification."""
    unique_slugs = sorted({slug for slug in slugs if slug})
    payload: dict[str, object] = {"entity": entity}
    if unique_slugs:
        payload["slugs"] = unique_slugs
    body = json.dumps(payload, separators=(",", ":"))
    timestamp = str(int(now if now is not None else time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Revalidate-Timestamp": timestamp,
        "X-Revalidate-Signature": sign_payload(secret, timestamp, body),
    }
    return body, headers


async def send_storefront_notification(
    entity: StorefrontEntity,
    slugs: Iterable[str | None] = (),
) -> None:
    """POST one notification. Logs and swallows every failure."""
    settings = get_settings()
    url = settings.storefront_revalidate_url
    secret = settings.storefront_revalidate_secret
    if not url or not secret:
        return

    body, headers = build_request(secret, entity, slugs)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=body, headers=headers)
        if response.status_code >= 400:
            logger.warning(
                "Storefront revalidate returned %s for %s",
                response.status_code,
                entity,
            )
    except Exception:
        logger.exception("Storefront revalidate failed for %s", entity)


def notify_storefront(
    entity: StorefrontEntity,
    slugs: Iterable[str | None] = (),
) -> None:
    """Schedule a notification without delaying the caller. Call after commit."""
    settings = get_settings()
    if not settings.storefront_revalidate_url or not settings.storefront_revalidate_secret:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Storefront revalidate skipped: no running event loop")
        return

    task = loop.create_task(send_storefront_notification(entity, list(slugs)))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
