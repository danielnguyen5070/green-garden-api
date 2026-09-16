"""Customer request/response schemas (admin only — customers never log in)."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import normalize_email
from app.core.text import normalize_phone

__all__ = [
    "CustomerCreate",
    "CustomerListResponse",
    "CustomerResponse",
    "CustomerStatusUpdate",
    "CustomerUpdate",
    "validate_phone",
]

_PHONE_PATTERN = re.compile(r"^\+?[0-9().-]{6,32}$")
_PHONE_MIN_DIGITS = 6


def validate_phone(value: str) -> str:
    """Normalize and sanity-check a phone number (the customer identity key)."""
    normalized = normalize_phone(value)
    if not normalized:
        raise ValueError("Phone is required")
    if len(normalized) > 32:
        raise ValueError("Phone must be at most 32 characters")
    digits = sum(1 for char in normalized if char.isdigit())
    if not _PHONE_PATTERN.match(normalized) or digits < _PHONE_MIN_DIGITS:
        raise ValueError("Phone must be a valid phone number")
    return normalized


class CustomerCreate(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None

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

    @field_validator("email", mode="before")
    @classmethod
    def normalize_customer_email(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = normalize_email(value)
            return normalized or None
        return value


class CustomerUpdate(BaseModel):
    phone: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None

    @field_validator("phone")
    @classmethod
    def normalize_customer_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_phone(value)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be empty")
        return stripped

    @field_validator("email", mode="before")
    @classmethod
    def normalize_customer_email(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = normalize_email(value)
            return normalized or None
        return value


class CustomerStatusUpdate(BaseModel):
    is_active: bool


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phone: str
    name: str
    email: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    page: int
    page_size: int
    total: int
