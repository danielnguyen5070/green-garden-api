from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.plant import Plant


class PlantPotSize(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Optional pot size variant for a plant (e.g. Small / Medium / Large)."""

    __tablename__ = "plant_pot_sizes"
    __table_args__ = (
        CheckConstraint(
            "price_adjustment >= 0",
            name="ck_plant_pot_sizes_price_adjustment_non_negative",
        ),
        Index("ix_plant_pot_sizes_plant_id", "plant_id"),
    )

    plant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    price_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        server_default="0",
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    plant: Mapped[Plant] = relationship("Plant", back_populates="pot_sizes")
