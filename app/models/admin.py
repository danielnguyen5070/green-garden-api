from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Admin(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Admin users who can access /admin (JWT cookie auth)."""

    __tablename__ = "admins"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # UNIQUE creates a unique index suitable for login lookups
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
