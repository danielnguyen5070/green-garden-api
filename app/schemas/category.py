"""Category request/response schemas (admin + public storefront)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from app.core.text import normalize_slug


class CategorySummary(BaseModel):
    """Minimal category information embedded in other responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    description: str | None = None
    image_url: AnyHttpUrl | None = None
    sort_order: int = Field(default=0, ge=0)
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
    def normalize_category_slug(cls, value: str) -> str:
        normalized = normalize_slug(value)
        if not normalized:
            raise ValueError("Slug must contain letters or digits")
        return normalized

    @field_validator("image_url")
    @classmethod
    def image_url_within_column_length(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and len(str(value)) > 1024:
            raise ValueError("Image URL must be at most 1024 characters")
        return value


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    image_url: AnyHttpUrl | None = None
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

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("slug")
    @classmethod
    def normalize_category_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_slug(value)
        if not normalized:
            raise ValueError("Slug must contain letters or digits")
        return normalized

    @field_validator("image_url")
    @classmethod
    def image_url_within_column_length(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and len(str(value)) > 1024:
            raise ValueError("Image URL must be at most 1024 characters")
        return value


class CategoryStatusUpdate(BaseModel):
    is_active: bool


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None
    image_url: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# Listings expose the same fields as the detail response today; kept as a
# separate name so list rows can diverge without breaking the detail contract.
class CategoryListItem(CategoryResponse):
    pass


class CategoryListResponse(BaseModel):
    items: list[CategoryListItem]
    page: int
    page_size: int
    total: int


class PublicCategoryListItem(BaseModel):
    """Storefront row — no audit timestamps or status bookkeeping."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None
    image_url: str | None
    sort_order: int


class PublicCategoryListResponse(BaseModel):
    items: list[PublicCategoryListItem]
    page: int
    page_size: int
    total: int
