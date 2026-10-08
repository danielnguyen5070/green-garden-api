"""Bank transfer payments through SePay (VietQR to a fixed VA + payment code).

The shop has one SePay-linked account (a fixed virtual account). Each
bank-transfer order gets a unique `payment_reference` that the customer puts in
the transfer content; SePay extracts it into the webhook's `code` field.

Webhook processing is idempotent: the transaction is inserted keyed by SePay's
transaction `id` with `ON CONFLICT DO NOTHING`, and only the delivery that
inserted the row may touch the order. The order row is locked while it is
checked, so two different transactions for one order cannot both apply.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NamedTuple
from urllib.parse import urlencode

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.config import Settings, get_settings
from app.features.orders.models import Order, PaymentMethod, PaymentStatus
from app.features.payments.models import (
    PaymentMatchStatus,
    PaymentProvider,
    PaymentTransaction,
)
from app.features.payments.schemas import SePayWebhookPayload

_QR_BASE_URL = "https://qr.sepay.vn/img"
# Matches `payment_reference_for`: "GG" + YYYYMMDD + 4-digit daily sequence.
_REFERENCE_PATTERN = re.compile(r"GG\d{12}", re.IGNORECASE)


class BankTransferDetails(NamedTuple):
    bank_code: str
    bank_name: str
    account_number: str
    account_holder: str | None
    amount: Decimal
    reference: str
    qr_url: str


def bank_transfer_info(
    order: Order,
    settings: Settings | None = None,
) -> BankTransferDetails | None:
    """What the customer needs to pay `order` by transfer, or `None` for COD."""
    settings = settings or get_settings()
    if (
        order.payment_method is not PaymentMethod.BANK_TRANSFER
        or order.payment_reference is None
        or not settings.sepay_account_number
    ):
        return None

    # VND has no minor unit on bank transfers.
    amount = order.total_amount.quantize(Decimal("1"))
    query = {
        "acc": settings.sepay_account_number,
        "bank": settings.sepay_bank_code,
        "amount": str(amount),
        "des": order.payment_reference,
        "template": "compact",
    }
    return BankTransferDetails(
        bank_code=settings.sepay_bank_code,
        bank_name=settings.sepay_bank_name or settings.sepay_bank_code,
        account_number=settings.sepay_account_number,
        account_holder=settings.sepay_account_holder,
        amount=amount,
        reference=order.payment_reference,
        qr_url=f"{_QR_BASE_URL}?{urlencode(query)}",
    )


def _candidate_references(payload: SePayWebhookPayload) -> list[str]:
    """`code` first (SePay's own extraction), then any match in `content`."""
    candidates: list[str] = []
    if payload.code:
        candidates.append(payload.code.strip().upper())
    for text in (payload.content, payload.description):
        if text:
            candidates.extend(match.upper() for match in _REFERENCE_PATTERN.findall(text))
    return list(dict.fromkeys(candidates))


async def _lock_order_by_reference(
    session: AsyncSession,
    references: list[str],
) -> Order | None:
    if not references:
        return None
    result = await session.execute(
        select(Order)
        .where(
            Order.payment_reference.in_(references),
            Order.payment_method == PaymentMethod.BANK_TRANSFER,
        )
        .options(noload(Order.customer), noload(Order.items))
        .order_by(Order.created_at)
        .limit(1)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def process_sepay_webhook(
    session: AsyncSession,
    payload: SePayWebhookPayload,
    raw_payload: dict[str, Any],
) -> PaymentMatchStatus | None:
    """
    Record one SePay transaction and settle the order it pays.

    Returns what happened to the transaction, or `None` when it was already
    recorded by an earlier delivery (nothing is changed then).
    """
    try:
        inserted = await session.execute(
            insert(PaymentTransaction)
            .values(
                provider=PaymentProvider.SEPAY.value,
                provider_transaction_id=payload.id,
                gateway=payload.gateway,
                account_number=payload.account_number,
                sub_account=payload.sub_account,
                code=payload.code,
                content=payload.content,
                transfer_type=payload.transfer_type,
                transfer_amount=payload.transfer_amount,
                reference_code=payload.reference_code,
                transaction_date=payload.transaction_date,
                match_status=PaymentMatchStatus.UNMATCHED.value,
                raw_payload=raw_payload,
            )
            .on_conflict_do_nothing(
                index_elements=["provider", "provider_transaction_id"]
            )
            .returning(PaymentTransaction.id)
        )
        transaction_id: uuid.UUID | None = inserted.scalar_one_or_none()
        if transaction_id is None:
            await session.rollback()
            return None

        order_id: uuid.UUID | None = None
        if payload.transfer_type != "in":
            match_status = PaymentMatchStatus.IGNORED
        else:
            order = await _lock_order_by_reference(session, _candidate_references(payload))
            if order is None:
                match_status = PaymentMatchStatus.UNMATCHED
            else:
                order_id = order.id
                if order.payment_status is PaymentStatus.PAID:
                    match_status = PaymentMatchStatus.ALREADY_PAID
                elif payload.transfer_amount != order.total_amount:
                    match_status = PaymentMatchStatus.AMOUNT_MISMATCH
                else:
                    order.payment_status = PaymentStatus.PAID
                    order.paid_at = datetime.now(UTC)
                    match_status = PaymentMatchStatus.MATCHED

        await session.execute(
            update(PaymentTransaction)
            .where(PaymentTransaction.id == transaction_id)
            .values(order_id=order_id, match_status=match_status.value)
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return match_status
