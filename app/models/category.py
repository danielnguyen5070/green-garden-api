from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.plant import Plant


class Category(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Product category containing many plants."""

    __tablename__ = "categories"
    __table_args__ = (
        Index("ix_categories_name", "name"),
        Index("ix_categories_is_active", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # UNIQUE creates a unique index on slug
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    plants: Mapped[list[Plant]] = relationship(
        "Plant",
        back_populates="category",
        lazy="selectin",
    )
