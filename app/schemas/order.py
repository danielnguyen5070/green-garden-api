"""Order request/response schemas (admin only).

The client never sends prices: `unit_price` and `total_amount` are always
calculated by the backend from the current plant price plus the selected pot
size adjustment, so any money field in the request body is ignored.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import normalize_email
from app.models.order import OrderStatus
from app.schemas.customer import validate_phone

__all__ = [
    "OrderCreate",
    "OrderCustomerCreate",
    "OrderCustomerResponse",
    "OrderItemCreate",
    "OrderItemResponse",
    "OrderListResponse",
    "OrderResponse",
    "OrderStatusUpdate",
    "StorefrontOrderCreate",
    "StorefrontOrderCustomer",
    "StorefrontOrderResponse",
]

# `shipping_address` and `note` are TEXT columns: these caps only keep the
# public checkout from accepting unbounded payloads.
_MAX_SHIPPING_ADDRESS_LENGTH = 1000
_MAX_NOTE_LENGTH = 1000
_MAX_CHECKOUT_ITEMS = 50


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
    pot_size: str | None = Field(default=None, max_length=100)

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


class StorefrontOrderCreate(BaseModel):
    """
    Public checkout payload (cash on delivery).

    Only the name, phone, address, note and lines are read. Any price or total
    in the body is ignored — the backend prices the order from the catalogue.
    """

    customer: StorefrontOrderCustomer
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
    total_amount: Decimal
    shipping_address: str
    note: str | None
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
    """Checkout confirmation — what the thank-you page needs, nothing more."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime
