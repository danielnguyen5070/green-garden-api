"""Self-hosted bot protection for the public storefront forms.

Two checks, no external service and no IP tracking:

- every public form carries a honeypot (`website`) that must stay empty and a
  fill time (`form_elapsed_ms`) that must reach `MIN_FORM_FILL_MS`;
- checkout additionally allows at most `CHECKOUT_PHONE_LIMIT` orders per
  canonical phone number within `CHECKOUT_PHONE_WINDOW`, counted straight from
  the existing `orders` table.

Routes run these before calling the order or review services, so the bot
signals never reach the business logic.
"""

from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ErrorCode, ForbiddenError, RateLimitedError
from app.core.text import normalize_vn_phone
from app.features.customers.models import Customer
from app.features.orders.models import Order
from app.shared.bot_protection.schemas import BotSignals

MIN_FORM_FILL_MS = 3000
CHECKOUT_PHONE_LIMIT = 3
CHECKOUT_PHONE_WINDOW = timedelta(hours=1)


class BotSignalRejectedError(ForbiddenError):
    """
    Raised when the honeypot is filled or the form was submitted too fast.

    The client only ever sees the generic message; the reason is logged.
    """

    error_code = ErrorCode.SUBMISSION_REJECTED
    message = "Submission rejected"

    def __init__(self, reason: str) -> None:
        super().__init__(log_detail=reason)
        self.reason = reason


class CheckoutRateLimitedError(RateLimitedError):
    """Raised when a phone number has placed too many orders recently."""

    message = "Too many orders for this phone number. Please try again later."

    def __init__(self, retry_after: int) -> None:
        super().__init__(headers={"Retry-After": str(retry_after)})
        self.retry_after = retry_after


def verify_bot_signals(signals: BotSignals) -> None:
    """Reject a filled honeypot and a missing or too-short fill time."""
    if signals.website:
        raise BotSignalRejectedError("Honeypot field was filled")
    if signals.form_elapsed_ms is None or signals.form_elapsed_ms < MIN_FORM_FILL_MS:
        raise BotSignalRejectedError("Form was submitted too quickly")


async def check_checkout_phone_limit(session: AsyncSession, phone: str) -> None:
    """
    Raise `CheckoutRateLimitedError` once the phone is at its hourly limit.

    The window is measured with the database clock, the same clock that sets
    `orders.created_at`. `retry_after` is the number of seconds until the
    oldest of the newest `CHECKOUT_PHONE_LIMIT` orders leaves the window.
    """
    canonical = normalize_vn_phone(phone)
    now = func.now()
    result = await session.execute(
        select(Order.created_at, now)
        .join(Customer, Order.customer_id == Customer.id)
        .where(
            Customer.phone == canonical,
            Order.created_at >= now - CHECKOUT_PHONE_WINDOW,
        )
        .order_by(Order.created_at.desc())
        .limit(CHECKOUT_PHONE_LIMIT)
    )
    rows = result.all()
    if len(rows) < CHECKOUT_PHONE_LIMIT:
        return

    oldest_counted, db_now = rows[-1]
    remaining = (oldest_counted + CHECKOUT_PHONE_WINDOW - db_now).total_seconds()
    raise CheckoutRateLimitedError(retry_after=max(1, math.ceil(remaining)))
