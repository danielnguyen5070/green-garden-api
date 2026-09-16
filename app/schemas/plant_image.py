"""Plant image (media URL) request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from app.models.plant_image import PlantImageType


class PlantImageCreate(BaseModel):
    url: AnyHttpUrl
    type: PlantImageType = PlantImageType.IMAGE
    alt_text: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("url")
    @classmethod
    def url_within_column_length(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(value)) > 1024:
            raise ValueError("URL must be at most 1024 characters")
        return value

    @field_validator("alt_text")
    @classmethod
    def strip_alt_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class PlantImageUpdate(BaseModel):
    url: AnyHttpUrl | None = None
    type: PlantImageType | None = None
    alt_text: str | None = Field(default=None, max_length=255)
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("url")
    @classmethod
    def url_within_column_length(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and len(str(value)) > 1024:
            raise ValueError("URL must be at most 1024 characters")
        return value

    @field_validator("alt_text")
    @classmethod
    def strip_alt_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class PlantImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plant_id: UUID
    url: str
    type: PlantImageType
    alt_text: str | None
    sort_order: int
    created_at: datetime
