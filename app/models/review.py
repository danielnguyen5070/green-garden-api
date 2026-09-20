from __future__ import annotations

import enum

from sqlalchemy import CheckConstraint, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Review(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Website-wide customer review (not tied to a plant). Moderated before publish."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_reviews_rating_range",
        ),
        Index("ix_reviews_status", "status"),
        Index("ix_reviews_created_at", "created_at"),
        # Public catalogue filters by status then sorts by newest.
        Index("ix_reviews_status_created_at", "status", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(
            ReviewStatus,
            name="review_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
