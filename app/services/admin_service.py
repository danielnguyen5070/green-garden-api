"""Admin management business logic."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, normalize_email, validate_password_strength
from app.models.admin import Admin
from app.services.auth_service import get_admin_by_email, get_admin_by_id


class AdminNotFoundError(Exception):
    """Raised when an admin id does not exist."""


class EmailConflictError(Exception):
    """Raised when an email is already used by another admin."""


class SelfDeactivationError(Exception):
    """Raised when an admin tries to deactivate their own account."""


async def list_admins(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> tuple[list[Admin], int]:
    total_result = await session.execute(select(func.count()).select_from(Admin))
    total = int(total_result.scalar_one())

    offset = (page - 1) * page_size
    result = await session.execute(
        select(Admin)
        .order_by(Admin.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    return list(result.scalars().all()), total


async def get_admin(session: AsyncSession, admin_id: uuid.UUID) -> Admin:
    admin = await get_admin_by_id(session, admin_id)
    if admin is None:
        raise AdminNotFoundError("Admin not found")
    return admin


async def create_admin_account(
    session: AsyncSession,
    *,
    name: str,
    email: str,
    password: str,
) -> Admin:
    validate_password_strength(password)
    normalized = normalize_email(email)
    existing = await get_admin_by_email(session, normalized)
    if existing is not None:
        raise EmailConflictError(f"Admin with email '{normalized}' already exists")

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


async def update_admin(
    session: AsyncSession,
    admin_id: uuid.UUID,
    *,
    name: str | None = None,
    email: str | None = None,
    is_active: bool | None = None,
    current_admin_id: uuid.UUID | None = None,
) -> Admin:
    admin = await get_admin(session, admin_id)

    if name is not None:
        admin.name = name.strip()

    if email is not None:
        normalized = normalize_email(email)
        if normalized != admin.email:
            existing = await get_admin_by_email(session, normalized)
            if existing is not None and existing.id != admin.id:
                raise EmailConflictError(
                    f"Admin with email '{normalized}' already exists"
                )
            admin.email = normalized

    if is_active is not None:
        if (
            current_admin_id is not None
            and admin.id == current_admin_id
            and is_active is False
        ):
            raise SelfDeactivationError("Cannot deactivate your own account")
        admin.is_active = is_active

    await session.commit()
    await session.refresh(admin)
    return admin


async def update_admin_status(
    session: AsyncSession,
    admin_id: uuid.UUID,
    *,
    is_active: bool,
    current_admin_id: uuid.UUID,
) -> Admin:
    return await update_admin(
        session,
        admin_id,
        is_active=is_active,
        current_admin_id=current_admin_id,
    )


async def change_admin_password(
    session: AsyncSession,
    admin_id: uuid.UUID,
    *,
    password: str,
) -> Admin:
    validate_password_strength(password)
    admin = await get_admin(session, admin_id)
    admin.password_hash = hash_password(password)
    await session.commit()
    await session.refresh(admin)
    return admin
