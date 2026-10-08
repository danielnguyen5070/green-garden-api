from __future__ import annotations

import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentProvider(str, enum.Enum):
    SEPAY = "sepay"


class PaymentMatchStatus(str, enum.Enum):
    """What a received transaction did to the order it names, if any."""

    MATCHED = "matched"
    AMOUNT_MISMATCH = "amount_mismatch"
    ALREADY_PAID = "already_paid"
    UNMATCHED = "unmatched"
    IGNORED = "ignored"


class PaymentTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One bank transaction reported by SePay, stored exactly once.

    The unique `(provider, provider_transaction_id)` pair is what makes webhook
    processing idempotent: a retried delivery cannot insert a second row.
    """

    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_transaction_id",
            name="uq_payment_transactions_provider_transaction_id",
        ),
        Index("ix_payment_transactions_order_id", "order_id"),
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PaymentProvider.SEPAY.value,
        server_default=PaymentProvider.SEPAY.value,
    )
    provider_transaction_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    gateway: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sub_account: Mapped[str | None] = mapped_column(String(250), nullable=True)
    code: Mapped[str | None] = mapped_column(String(250), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    transfer_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    transfer_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reference_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # As sent by SePay ("YYYY-MM-DD HH:MM:SS", Vietnam local time).
    transaction_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
