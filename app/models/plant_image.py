from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.plant import Plant


class PlantImageType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class PlantImage(Base, UUIDPrimaryKeyMixin):
    """External media URL for a plant (image or video). No binary storage."""

    __tablename__ = "plant_images"
    __table_args__ = (Index("ix_plant_images_plant_id", "plant_id"),)

    plant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    type: Mapped[PlantImageType] = mapped_column(
        Enum(
            PlantImageType,
            name="plant_image_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=PlantImageType.IMAGE,
    )
    alt_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    plant: Mapped[Plant] = relationship("Plant", back_populates="images")
