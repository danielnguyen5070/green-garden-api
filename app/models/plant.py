from __future__ import annotations

import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
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


class PlantType(str, enum.Enum):
    FOLIAGE = "foliage"
    FLOWERING = "flowering"
    SUCCULENT = "succulent"
    CACTUS = "cactus"
    HERB = "herb"
    FERN = "fern"
    VINE = "vine"
    TREE = "tree"
    PALM = "palm"
    BAMBOO = "bamboo"
    AQUATIC = "aquatic"
    OTHER = "other"


class PlantDifficulty(str, enum.Enum):
    EASY = "easy"
    MODERATE = "moderate"
    HARD = "hard"


class PlantGrowthRate(str, enum.Enum):
    SLOW = "slow"
    MODERATE = "moderate"
    FAST = "fast"


class PlantSunlight(str, enum.Enum):
    FULL_SUN = "full_sun"
    PARTIAL_SUN = "partial_sun"
    PARTIAL_SHADE = "partial_shade"
    SHADE = "shade"
    LOW_LIGHT = "low_light"


class PlantWatering(str, enum.Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class PlantSpaceRequirement(str, enum.Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class Plant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Sellable plant product."""

    __tablename__ = "plants"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_plants_price_non_negative"),
        # NULL price_vi passes the check: the Vietnamese price is optional
        CheckConstraint("price_vi >= 0", name="ck_plants_price_vi_non_negative"),
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
    # Vietnamese copy/pricing is optional; the unprefixed columns are the default locale
    name_vi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_vi: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Long-form SEO copy; separate from the short catalogue `description`.
    long_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    long_description_vi: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    price_vi: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # Care / suitability attributes (optional until filled in by admin).
    plant_type: Mapped[PlantType | None] = mapped_column(
        Enum(
            PlantType,
            name="plant_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    difficulty: Mapped[PlantDifficulty | None] = mapped_column(
        Enum(
            PlantDifficulty,
            name="plant_difficulty",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    growth_rate: Mapped[PlantGrowthRate | None] = mapped_column(
        Enum(
            PlantGrowthRate,
            name="plant_growth_rate",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    sunlight: Mapped[PlantSunlight | None] = mapped_column(
        Enum(
            PlantSunlight,
            name="plant_sunlight",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    watering: Mapped[PlantWatering | None] = mapped_column(
        Enum(
            PlantWatering,
            name="plant_watering",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    space_requirement: Mapped[PlantSpaceRequirement | None] = mapped_column(
        Enum(
            PlantSpaceRequirement,
            name="plant_space_requirement",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    indoor_suitable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outdoor_suitable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pet_safe: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    beginner_friendly: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

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
