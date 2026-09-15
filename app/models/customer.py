from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.order import Order


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Guest customer identified by phone number (no accounts / login)."""

    __tablename__ = "customers"

    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    orders: Mapped[list[Order]] = relationship(
        "Order",
        back_populates="customer",
        lazy="selectin",
    )
