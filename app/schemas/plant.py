"""Plant request/response schemas (admin + public storefront)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.text import normalize_slug, normalize_sku
from app.schemas.category import CategorySummary
from app.schemas.plant_image import PlantImageResponse
from app.schemas.plant_pot_size import PlantPotSizeResponse

__all__ = [
    "CategorySummary",
    "PlantCreate",
    "PlantListItem",
    "PlantListResponse",
    "PlantResponse",
    "PlantStatusUpdate",
    "PlantUpdate",
    "PublicPlantDetail",
    "PublicPlantListItem",
    "PublicPlantListResponse",
]


class PlantCreate(BaseModel):
    category_id: UUID
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    sku: str = Field(min_length=1, max_length=100)
    is_featured: bool = False
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name is required")
        return stripped

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("slug")
    @classmethod
    def normalize_plant_slug(cls, value: str) -> str:
        normalized = normalize_slug(value)
        if not normalized:
            raise ValueError("Slug must contain letters or digits")
        return normalized

    @field_validator("sku")
    @classmethod
    def normalize_plant_sku(cls, value: str) -> str:
        normalized = normalize_sku(value)
        if not normalized:
            raise ValueError("SKU is required")
        return normalized


class PlantUpdate(BaseModel):
    category_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    is_featured: bool | None = None
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

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("slug")
    @classmethod
    def normalize_plant_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_slug(value)
        if not normalized:
            raise ValueError("Slug must contain letters or digits")
        return normalized

    @field_validator("sku")
    @classmethod
    def normalize_plant_sku(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_sku(value)
        if not normalized:
            raise ValueError("SKU cannot be empty")
        return normalized


class PlantStatusUpdate(BaseModel):
    is_active: bool


class PlantListItem(BaseModel):
    """Lightweight row for plant listings (no images / pot sizes)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    category: CategorySummary | None = None
    name: str
    slug: str
    price: Decimal
    stock: int
    sku: str
    is_featured: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PlantResponse(BaseModel):
    """Full plant detail including category, images and pot sizes."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    category: CategorySummary | None = None
    name: str
    slug: str
    description: str | None
    price: Decimal
    stock: int
    sku: str
    is_featured: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    images: list[PlantImageResponse] = []
    pot_sizes: list[PlantPotSizeResponse] = []


class PlantListResponse(BaseModel):
    items: list[PlantListItem]
    page: int
    page_size: int
    total: int


class PublicPlantListItem(BaseModel):
    """Storefront listing row — no SKU / stock bookkeeping fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    price: Decimal
    is_featured: bool
    category: CategorySummary | None = None


class PublicPlantListResponse(BaseModel):
    items: list[PublicPlantListItem]
    page: int
    page_size: int
    total: int


class PublicPlantDetail(BaseModel):
    """Storefront detail — excludes SKU, is_active and audit timestamps."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None
    price: Decimal
    is_featured: bool
    in_stock: bool
    category: CategorySummary | None = None
    images: list[PlantImageResponse] = []
    pot_sizes: list[PlantPotSizeResponse] = []
