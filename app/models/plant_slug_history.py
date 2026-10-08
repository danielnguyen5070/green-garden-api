from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.plant import Plant


class PlantSlugHistory(Base, UUIDPrimaryKeyMixin):
    """A slug a plant used before, kept so old storefront URLs still resolve."""

    __tablename__ = "plant_slug_history"
    __table_args__ = (Index("ix_plant_slug_history_plant_id", "plant_id"),)

    plant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # A slug maps to at most one plant; a live `plants.slug` always wins over history.
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    plant: Mapped[Plant] = relationship("Plant", back_populates="slug_history")
