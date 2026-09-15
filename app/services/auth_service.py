"""Admin authentication business logic.

TODO(production): Add rate limiting for POST /api/v1/auth/login
(e.g. per-IP / per-email) before exposing this endpoint publicly.
Session-based refresh token rotation can be added later without changing
the public API contract.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    normalize_email,
    verify_password,
)
from app.models.admin import Admin


class AuthenticationError(Exception):
    """Raised when authentication or token validation fails."""


async def get_admin_by_email(session: AsyncSession, email: str) -> Admin | None:
    normalized = normalize_email(email)
    result = await session.execute(select(Admin).where(Admin.email == normalized))
    return result.scalar_one_or_none()


async def get_admin_by_id(session: AsyncSession, admin_id: uuid.UUID) -> Admin | None:
    result = await session.execute(select(Admin).where(Admin.id == admin_id))
    return result.scalar_one_or_none()


async def authenticate_admin(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> Admin:
    """
    Verify credentials for an active admin.

    Always raises AuthenticationError with a generic message on failure
    to avoid account enumeration.
    """
    admin = await get_admin_by_email(session, email)
    if admin is None or not admin.is_active:
        raise AuthenticationError("Invalid email or password")
    if not verify_password(password, admin.password_hash):
        raise AuthenticationError("Invalid email or password")
    return admin


def issue_token_pair(admin: Admin) -> tuple[str, str]:
    access = create_token(subject=admin.id, token_type="access")
    refresh = create_token(subject=admin.id, token_type="refresh")
    return access, refresh


async def resolve_admin_from_token(
    session: AsyncSession,
    *,
    token: str,
    expected_type: Literal["access", "refresh"],
) -> Admin:
    try:
        payload = decode_token(token, expected_type=expected_type)
        admin_id = uuid.UUID(str(payload["sub"]))
    except Exception as exc:
        raise AuthenticationError("Could not validate credentials") from exc

    admin = await get_admin_by_id(session, admin_id)
    if admin is None or not admin.is_active:
        raise AuthenticationError("Could not validate credentials")
    return admin


async def create_admin(
    session: AsyncSession,
    *,
    name: str,
    email: str,
    password: str,
) -> Admin:
    """Create an admin with a hashed password (CLI / bootstrap only)."""
    normalized = normalize_email(email)
    existing = await get_admin_by_email(session, normalized)
    if existing is not None:
        raise ValueError(f"Admin with email '{normalized}' already exists")

    admin = Admin(
        name=name.strip(),
        email=normalized,
        password_hash=hash_password(password),
        is_active=True,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return admin
