"""Plant pot size request/response schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlantPotSizeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # DB enforces price_adjustment >= 0 (ck_plant_pot_sizes_price_adjustment_non_negative)
    price_adjustment: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2
    )
    # Applied on top of the plant's Vietnamese price; omit when there is none
    price_adjustment_vi: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name is required")
        return stripped


class PlantPotSizeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price_adjustment: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    price_adjustment_vi: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be empty")
        return stripped


class PlantPotSizeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plant_id: UUID
    name: str
    price_adjustment: Decimal
    price_adjustment_vi: Decimal | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
