"""Payment provider callbacks.

`POST /payments/sepay/webhook` receives SePay's bank transaction notifications.
SePay authenticates with `Authorization: Apikey <key>` and counts a delivery as
successful only on HTTP 200/201 with `{"success": true}`; anything else is
retried, which is safe because processing is idempotent on SePay's `id`.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.payment import SePayWebhookPayload, SePayWebhookResponse
from app.services.payment_service import process_sepay_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

_APIKEY_SCHEME = "apikey"


def _verify_sepay_api_key(authorization: str | None) -> None:
    expected = get_settings().sepay_webhook_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SePay webhook is not configured",
        )
    scheme, _, key = (authorization or "").strip().partition(" ")
    if scheme.lower() != _APIKEY_SCHEME or not hmac.compare_digest(
        key.strip().encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@router.post(
    "/sepay/webhook",
    response_model=SePayWebhookResponse,
    summary="SePay transaction webhook",
    description=(
        "Called by SePay for every transaction on the linked account. The "
        "payment code (`code`, else a `GG` + 12-digit reference found in "
        "`content`) is matched to a bank-transfer order; when the incoming "
        "amount equals the order total the order's `payment_status` becomes "
        "`paid`. Every transaction is stored once by SePay `id`, so retries "
        "and duplicates change nothing. Unmatched, outgoing or wrong-amount "
        "transactions are recorded for review and still acknowledged."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or wrong API key"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "SePay webhook is not configured"
        },
    },
)
async def post_sepay_webhook(
    raw_payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> SePayWebhookResponse:
    _verify_sepay_api_key(authorization)
    try:
        payload = SePayWebhookPayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_url=False, include_context=False),
        ) from exc

    result = await process_sepay_webhook(db, payload, raw_payload)
    logger.info(
        "SePay transaction %s: %s",
        payload.id,
        result.value if result is not None else "duplicate",
    )
    return SePayWebhookResponse(success=True)
