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
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.order_item import OrderItem
    from app.models.plant_image import PlantImage
    from app.models.plant_pot_size import PlantPotSize


class Plant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Sellable plant product."""

    __tablename__ = "plants"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_plants_price_non_negative"),
        CheckConstraint("stock >= 0", name="ck_plants_stock_non_negative"),
        Index("ix_plants_category_id", "category_id"),
        Index("ix_plants_is_active", "is_active"),
        Index("ix_plants_is_featured", "is_featured"),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    category: Mapped[Category] = relationship("Category", back_populates="plants")
    images: Mapped[list[PlantImage]] = relationship(
        "PlantImage",
        back_populates="plant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    pot_sizes: Mapped[list[PlantPotSize]] = relationship(
        "PlantPotSize",
        back_populates="plant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    order_items: Mapped[list[OrderItem]] = relationship(
        "OrderItem",
        back_populates="plant",
        lazy="selectin",
    )
