"""Review request/response schemas (admin + public storefront)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.review import ReviewStatus

__all__ = [
    "PublicReviewListItem",
    "PublicReviewListResponse",
    "ReviewCreate",
    "ReviewListItem",
    "ReviewListResponse",
    "ReviewResponse",
    "ReviewStatusUpdate",
]


class ReviewCreate(BaseModel):
    """Public storefront submission — always starts as `pending`."""

    name: str = Field(min_length=1, max_length=255)
    rating: int = Field(ge=1, le=5)
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name is required")
        return stripped

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Content is required")
        return stripped


class ReviewStatusUpdate(BaseModel):
    status: ReviewStatus


class ReviewResponse(BaseModel):
    """Full review row for the admin panel."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    rating: int
    content: str
    status: ReviewStatus
    created_at: datetime
    updated_at: datetime


class ReviewListItem(ReviewResponse):
    pass


class ReviewListResponse(BaseModel):
    items: list[ReviewListItem]
    page: int
    page_size: int
    total: int


class PublicReviewListItem(BaseModel):
    """Storefront card — approved reviews only, no moderation fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    rating: int
    content: str
    created_at: datetime


class PublicReviewListResponse(BaseModel):
    items: list[PublicReviewListItem]
    page: int
    page_size: int
    total: int
