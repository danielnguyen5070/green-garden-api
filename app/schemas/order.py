"""Order request/response schemas.

The client never sends prices: `unit_price`, `subtotal_amount`, `shipping_fee`
and `total_amount` are always calculated by the backend, in VND, from the
current plant price plus the selected pot size adjustment, so any money field in
the request body is ignored.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import normalize_email
from app.models.order import OrderStatus, PaymentMethod, PaymentStatus
from app.shared.bot_protection.schemas import BotSignals
from app.features.customers.schemas import validate_phone
from app.schemas.payment import BankTransferInfo

__all__ = [
    "OrderCreate",
    "OrderCustomerCreate",
    "OrderCustomerResponse",
    "OrderItemCreate",
    "OrderItemResponse",
    "OrderListResponse",
    "OrderResponse",
    "OrderStatusUpdate",
    "ShippingPolicyResponse",
    "StorefrontOrderCreate",
    "StorefrontOrderCustomer",
    "StorefrontOrderResponse",
    "StorefrontQuoteItem",
    "StorefrontQuoteLine",
    "StorefrontQuoteRequest",
    "StorefrontQuoteResponse",
]

# `shipping_address` and `note` are TEXT columns: these caps only keep the
# public checkout from accepting unbounded payloads.
_MAX_SHIPPING_ADDRESS_LENGTH = 1000
_MAX_NOTE_LENGTH = 1000
_MAX_CHECKOUT_ITEMS = 50
_MAX_QUOTE_QUANTITY = 999


class StorefrontOrderCustomer(BaseModel):
    """Checkout identity: the phone that identifies the customer, and a name."""

    phone: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)

    @field_validator("phone")
    @classmethod
    def normalize_customer_phone(cls, value: str) -> str:
        return validate_phone(value)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name is required")
        return stripped


class OrderCustomerCreate(StorefrontOrderCustomer):
    """Admin checkout customer block — the storefront never sends an email."""

    email: EmailStr | None = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_customer_email(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = normalize_email(value)
            return normalized or None
        return value


class OrderItemCreate(BaseModel):
    plant_id: UUID
    quantity: int = Field(ge=1)
    pot_size_id: UUID | None = None
    pot_size: str | None = Field(
        default=None,
        max_length=100,
        description="Deprecated: pot size name. Send `pot_size_id` instead.",
    )

    @field_validator("pot_size")
    @classmethod
    def strip_pot_size(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class OrderCreate(BaseModel):
    customer: OrderCustomerCreate
    shipping_address: str = Field(min_length=1)
    note: str | None = None
    items: list[OrderItemCreate] = Field(min_length=1)

    @field_validator("shipping_address")
    @classmethod
    def strip_shipping_address(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Shipping address is required")
        return stripped

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class StorefrontOrderCreate(BotSignals):
    """
    Public checkout payload (cash on delivery or bank transfer).

    Only the name, phone, address, note, lines and payment method are read,
    plus the bot signals checked before the order is created. Any price or
    total in the body is ignored — the backend prices the order from the
    catalogue. Without `payment_method` the order is cash on delivery.
    """

    customer: StorefrontOrderCustomer
    payment_method: PaymentMethod = PaymentMethod.COD
    shipping_address: str = Field(
        min_length=1,
        max_length=_MAX_SHIPPING_ADDRESS_LENGTH,
    )
    note: str | None = Field(default=None, max_length=_MAX_NOTE_LENGTH)
    items: list[OrderItemCreate] = Field(
        min_length=1,
        max_length=_MAX_CHECKOUT_ITEMS,
    )

    @field_validator("shipping_address")
    @classmethod
    def strip_shipping_address(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Shipping address is required")
        return stripped

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class OrderCustomerResponse(BaseModel):
    """Customer information embedded in order responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str
    email: str | None


class OrderItemResponse(BaseModel):
    """Snapshot line item — never re-read from the current plant record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plant_id: UUID
    plant_name: str
    quantity: int
    unit_price: Decimal
    pot_size: str | None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    status: OrderStatus
    currency: str
    subtotal_amount: Decimal
    shipping_fee: Decimal
    total_amount: Decimal
    shipping_address: str
    note: str | None
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    payment_reference: str | None
    paid_at: datetime | None
    customer: OrderCustomerResponse
    items: list[OrderItemResponse] = []
    created_at: datetime
    updated_at: datetime


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    page: int
    page_size: int
    total: int


class StorefrontOrderResponse(BaseModel):
    """
    Checkout confirmation — what the thank-you page needs, nothing more.

    `payment` carries the transfer details for bank-transfer orders and is
    null for cash on delivery.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    status: OrderStatus
    currency: str
    subtotal_amount: Decimal
    shipping_fee: Decimal
    total_amount: Decimal
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    payment_reference: str | None
    paid_at: datetime | None
    payment: BankTransferInfo | None = None
    created_at: datetime


class StorefrontQuoteItem(BaseModel):
    """A cart line: only the selection, never a price."""

    plant_id: UUID
    quantity: int = Field(ge=1, le=_MAX_QUOTE_QUANTITY)
    pot_size_id: UUID | None = None


class StorefrontQuoteRequest(BaseModel):
    items: list[StorefrontQuoteItem] = Field(max_length=_MAX_CHECKOUT_ITEMS)


class StorefrontQuoteLine(BaseModel):
    """
    One priced cart line.

    `available` is false when the plant is unknown, inactive, has no VND price
    or the pot size is no longer on sale; such a line costs nothing and the
    catalogue fields may be null. `max_quantity` is the plant's current stock.
    """

    plant_id: UUID
    pot_size_id: UUID | None
    quantity: int
    available: bool
    slug: str | None
    name: str | None
    name_vi: str | None
    image_url: str | None
    pot_size_name: str | None
    unit_price: Decimal
    line_total: Decimal
    max_quantity: int


class StorefrontQuoteResponse(BaseModel):
    """What checkout would charge right now, in `currency` (always VND)."""

    currency: str
    lines: list[StorefrontQuoteLine]
    subtotal_amount: Decimal
    shipping_fee: Decimal
    total_amount: Decimal
    free_shipping_above: Decimal
    amount_to_free_shipping: Decimal


class ShippingPolicyResponse(BaseModel):
    """Flat fee, waived when the subtotal is strictly above `free_shipping_above`."""

    currency: str
    shipping_fee: Decimal
    free_shipping_above: Decimal
