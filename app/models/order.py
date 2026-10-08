from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.order_item import OrderItem


ORDER_CURRENCY = "VND"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPING = "shipping"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentMethod(str, enum.Enum):
    COD = "cod"
    BANK_TRANSFER = "bank_transfer"


class PaymentStatus(str, enum.Enum):
    """`paid` is only ever set by a verified bank transfer; COD stays `pending`."""

    PENDING = "pending"
    PAID = "paid"


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Customer order with snapshot shipping address (no separate address table)."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_orders_total_amount_non_negative"),
        CheckConstraint("currency = 'VND'", name="ck_orders_currency_vnd"),
        CheckConstraint(
            "subtotal_amount >= 0", name="ck_orders_subtotal_amount_non_negative"
        ),
        CheckConstraint("shipping_fee >= 0", name="ck_orders_shipping_fee_non_negative"),
        CheckConstraint(
            "total_amount = subtotal_amount + shipping_fee",
            name="ck_orders_total_is_subtotal_plus_shipping",
        ),
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_payment_status", "payment_status"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            name="order_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=OrderStatus.PENDING,
        server_default=OrderStatus.PENDING.value,
    )
    # VND is the only transaction currency; the column makes that explicit.
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default=ORDER_CURRENCY,
        server_default=ORDER_CURRENCY,
    )
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0",
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_address: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(
            PaymentMethod,
            name="payment_method",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=PaymentMethod.COD,
        server_default=PaymentMethod.COD.value,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="payment_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
    )
    # Transfer content the customer must send; only set for bank transfers.
    payment_reference: Mapped[str | None] = mapped_column(
        String(32), unique=True, nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    customer: Mapped[Customer] = relationship("Customer", back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
