"""Category business logic."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.models.category import Category


class CategoryNotFoundError(Exception):
    """Raised when a category id or slug does not exist."""


class CategorySlugConflictError(Exception):
    """Raised when a category slug is already used."""


def _base_options() -> tuple[Any, ...]:
    """Category rows never need their plants collection loaded."""
    return (noload(Category.plants),)


async def _ensure_slug_available(
    session: AsyncSession,
    slug: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(Category.id).where(Category.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise CategorySlugConflictError(f"Category with slug '{slug}' already exists")


def _apply_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    is_active: bool | None,
) -> Select[Any]:
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Category.name.ilike(pattern), Category.slug.ilike(pattern))
        )
    if is_active is not None:
        stmt = stmt.where(Category.is_active.is_(is_active))
    return stmt


async def list_categories(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[Category], int]:
    """Ordered by `sort_order` then `created_at`, both ascending."""
    filters = {"search": search, "is_active": is_active}

    count_stmt = _apply_filters(select(func.count()).select_from(Category), **filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = _apply_filters(select(Category), **filters)
    stmt = (
        stmt.options(*_base_options())
        .order_by(Category.sort_order.asc(), Category.created_at.asc(), Category.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_category(session: AsyncSession, category_id: uuid.UUID) -> Category:
    result = await session.execute(
        select(Category).where(Category.id == category_id).options(*_base_options())
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise CategoryNotFoundError("Category not found")
    return category


async def create_category(
    session: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None,
    image_url: str | None,
    sort_order: int,
    is_active: bool,
) -> Category:
    await _ensure_slug_available(session, slug)

    category = Category(
        name=name,
        slug=slug,
        description=description,
        image_url=image_url,
        sort_order=sort_order,
        is_active=is_active,
    )
    session.add(category)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_category(session, category.id)


async def update_category(
    session: AsyncSession,
    category_id: uuid.UUID,
    *,
    name: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
    description_provided: bool = False,
    image_url_provided: bool = False,
) -> Category:
    category = await get_category(session, category_id)

    if slug is not None and slug != category.slug:
        await _ensure_slug_available(session, slug, exclude_id=category.id)
        category.slug = slug

    if name is not None:
        category.name = name
    if description_provided:
        category.description = description
    if image_url_provided:
        category.image_url = image_url
    if sort_order is not None:
        category.sort_order = sort_order
    # Deactivating a category intentionally leaves its plants untouched so
    # existing products and order history stay intact.
    if is_active is not None:
        category.is_active = is_active

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_category(session, category.id)


async def set_category_status(
    session: AsyncSession,
    category_id: uuid.UUID,
    *,
    is_active: bool,
) -> Category:
    category = await get_category(session, category_id)
    category.is_active = is_active
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_category(session, category.id)
