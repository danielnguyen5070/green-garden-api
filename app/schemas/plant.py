"""Plant request/response schemas (admin + public storefront)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from app.core.text import normalize_slug, normalize_sku
from app.models.plant import (
    PlantDifficulty,
    PlantGrowthRate,
    PlantSpaceRequirement,
    PlantSunlight,
    PlantType,
    PlantWatering,
)
from app.schemas.category import CategorySummary
from app.schemas.plant_image import PlantImageResponse, PublicPlantImage
from app.schemas.plant_pot_size import PlantPotSizeResponse

__all__ = [
    "CategorySummary",
    "PlantCreate",
    "PlantDifficulty",
    "PlantGrowthRate",
    "PlantListItem",
    "PlantListResponse",
    "PlantResponse",
    "PlantSpaceRequirement",
    "PlantStatusUpdate",
    "PlantSunlight",
    "PlantType",
    "PlantUpdate",
    "PlantWatering",
    "PublicPlantDetail",
    "PublicPlantListItem",
    "PublicPlantListResponse",
    "PublicPlantSearchResponse",
]


class PlantCreate(BaseModel):
    category_id: UUID
    name: str = Field(min_length=1, max_length=255)
    name_vi: str | None = Field(default=None, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    description: str | None = None
    description_vi: str | None = None
    long_description: str | None = None
    long_description_vi: str | None = None
    og_image_url: AnyHttpUrl | None = None
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    price_vi: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    sku: str = Field(min_length=1, max_length=100)
    is_featured: bool = False
    is_active: bool = True
    plant_type: PlantType | None = None
    difficulty: PlantDifficulty | None = None
    growth_rate: PlantGrowthRate | None = None
    sunlight: PlantSunlight | None = None
    watering: PlantWatering | None = None
    space_requirement: PlantSpaceRequirement | None = None
    indoor_suitable: bool | None = None
    outdoor_suitable: bool | None = None
    pet_safe: bool | None = None
    beginner_friendly: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name is required")
        return stripped

    @field_validator(
        "name_vi",
        "description",
        "description_vi",
        "long_description",
        "long_description_vi",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
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

    @field_validator("og_image_url")
    @classmethod
    def og_image_url_within_column_length(
        cls, value: AnyHttpUrl | None
    ) -> AnyHttpUrl | None:
        if value is not None and len(str(value)) > 1024:
            raise ValueError("OG image URL must be at most 1024 characters")
        return value


class PlantUpdate(BaseModel):
    category_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_vi: str | None = Field(default=None, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    description_vi: str | None = None
    long_description: str | None = None
    long_description_vi: str | None = None
    og_image_url: AnyHttpUrl | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    price_vi: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    is_featured: bool | None = None
    is_active: bool | None = None
    plant_type: PlantType | None = None
    difficulty: PlantDifficulty | None = None
    growth_rate: PlantGrowthRate | None = None
    sunlight: PlantSunlight | None = None
    watering: PlantWatering | None = None
    space_requirement: PlantSpaceRequirement | None = None
    indoor_suitable: bool | None = None
    outdoor_suitable: bool | None = None
    pet_safe: bool | None = None
    beginner_friendly: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be empty")
        return stripped

    @field_validator(
        "name_vi",
        "description",
        "description_vi",
        "long_description",
        "long_description_vi",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
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

    @field_validator("og_image_url")
    @classmethod
    def og_image_url_within_column_length(
        cls, value: AnyHttpUrl | None
    ) -> AnyHttpUrl | None:
        if value is not None and len(str(value)) > 1024:
            raise ValueError("OG image URL must be at most 1024 characters")
        return value


class PlantStatusUpdate(BaseModel):
    is_active: bool


class PlantListItem(BaseModel):
    """Lightweight row for plant listings (no images / pot sizes)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    category: CategorySummary | None = None
    name: str
    name_vi: str | None
    slug: str
    og_image_url: str | None
    price: Decimal
    price_vi: Decimal | None
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
    name_vi: str | None
    slug: str
    description: str | None
    description_vi: str | None
    long_description: str | None
    long_description_vi: str | None
    og_image_url: str | None
    price: Decimal
    price_vi: Decimal | None
    stock: int
    sku: str
    is_featured: bool
    is_active: bool
    plant_type: PlantType | None
    difficulty: PlantDifficulty | None
    growth_rate: PlantGrowthRate | None
    sunlight: PlantSunlight | None
    watering: PlantWatering | None
    space_requirement: PlantSpaceRequirement | None
    indoor_suitable: bool | None
    outdoor_suitable: bool | None
    pet_safe: bool | None
    beginner_friendly: bool | None
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
    """Storefront listing row — card data for the homepage, no SKU bookkeeping.

    Carries the copy, pricing and media the catalogue renders, so a listing
    never has to fetch each plant's detail endpoint.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    name_vi: str | None
    slug: str
    description: str | None
    description_vi: str | None
    og_image_url: str | None
    price: Decimal
    price_vi: Decimal | None
    stock: int
    is_featured: bool
    category: CategorySummary | None = None
    images: list[PublicPlantImage] = []


class PublicPlantListResponse(BaseModel):
    items: list[PublicPlantListItem]
    page: int
    page_size: int
    total: int


class PublicPlantSearchResponse(BaseModel):
    """Storefront keyword search — same card rows as the catalogue list."""

    query: str
    items: list[PublicPlantListItem]
    total: int


class PublicPlantDetail(BaseModel):
    """Storefront detail — excludes SKU, is_active and audit timestamps."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    name_vi: str | None
    slug: str
    description: str | None
    description_vi: str | None
    long_description: str | None
    long_description_vi: str | None
    og_image_url: str | None
    price: Decimal
    price_vi: Decimal | None
    is_featured: bool
    in_stock: bool
    plant_type: PlantType | None
    difficulty: PlantDifficulty | None
    growth_rate: PlantGrowthRate | None
    sunlight: PlantSunlight | None
    watering: PlantWatering | None
    space_requirement: PlantSpaceRequirement | None
    indoor_suitable: bool | None
    outdoor_suitable: bool | None
    pet_safe: bool | None
    beginner_friendly: bool | None
    category: CategorySummary | None = None
    images: list[PlantImageResponse] = []
    pot_sizes: list[PlantPotSizeResponse] = []
