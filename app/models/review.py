from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.plant import Plant


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Review(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Customer review, moderated before publish.

    `plant_id` NULL means a website-wide shop review; otherwise the review is
    about that plant.
    """

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
        # Plant detail page: approved reviews of one plant, newest first.
        Index(
            "ix_reviews_plant_id_status_created_at",
            "plant_id",
            "status",
            "created_at",
        ),
    )

    plant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plants.id", ondelete="CASCADE", name="fk_reviews_plant_id_plants"),
        nullable=True,
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

    plant: Mapped[Plant | None] = relationship("Plant", lazy="raise")
