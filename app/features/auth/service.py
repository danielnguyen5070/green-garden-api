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

from app.core.exceptions import ErrorCode, UnauthorizedError
from app.core.security import (
    create_token,
    decode_token,
    normalize_email,
    verify_password,
)
from app.features.admins.models import Admin


class AuthenticationError(UnauthorizedError):
    """Raised when authentication or token validation fails."""

    error_code = ErrorCode.INVALID_TOKEN
    message = "Could not validate credentials"


class InvalidCredentialsError(AuthenticationError):
    """Raised when the login email/password pair is wrong or the admin is inactive."""

    error_code = ErrorCode.INVALID_CREDENTIALS
    message = "Invalid email or password"


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
        raise InvalidCredentialsError()
    if not verify_password(password, admin.password_hash):
        raise InvalidCredentialsError()
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
        raise AuthenticationError(log_detail=f"Token rejected: {type(exc).__name__}") from exc

    admin = await get_admin_by_id(session, admin_id)
    if admin is None or not admin.is_active:
        raise AuthenticationError(log_detail="Token subject missing or inactive")
    return admin


async def create_admin(
    session: AsyncSession,
    *,
    name: str,
    email: str,
    password: str,
) -> Admin:
    """Create an admin with a hashed password (CLI / bootstrap)."""
    from app.features.admins.service import EmailConflictError, create_admin_account

    try:
        return await create_admin_account(
            session,
            name=name,
            email=email,
            password=password,
        )
    except EmailConflictError as exc:
        raise ValueError(str(exc)) from exc
