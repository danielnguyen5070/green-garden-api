"""Plant, plant image and pot size business logic."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.models.category import Category
from app.models.plant import Plant
from app.models.plant_image import PlantImage, PlantImageType
from app.models.plant_pot_size import PlantPotSize
from app.services.category_service import CategoryNotFoundError, get_category

SortField = Literal["created_at", "name", "price", "stock"]
SortOrder = Literal["asc", "desc"]

_SORT_COLUMNS = {
    "created_at": Plant.created_at,
    "name": Plant.name,
    "price": Plant.price,
    "stock": Plant.stock,
}


class PlantNotFoundError(Exception):
    """Raised when a plant id or slug does not exist."""


class PlantImageNotFoundError(Exception):
    """Raised when an image does not exist or belongs to another plant."""


class PlantPotSizeNotFoundError(Exception):
    """Raised when a pot size does not exist or belongs to another plant."""


class SlugConflictError(Exception):
    """Raised when a plant slug is already used."""


class SkuConflictError(Exception):
    """Raised when a plant SKU is already used."""


def _detail_options() -> tuple[Any, ...]:
    """Eager-load category, images and pot sizes; never walk back to plants."""
    return (
        selectinload(Plant.category).noload(Category.plants),
        selectinload(Plant.images),
        selectinload(Plant.pot_sizes),
        noload(Plant.order_items),
    )


def _list_options() -> tuple[Any, ...]:
    """Listings only need the category — skip media and variant collections."""
    return (
        selectinload(Plant.category).noload(Category.plants),
        noload(Plant.images),
        noload(Plant.pot_sizes),
        noload(Plant.order_items),
    )


async def _ensure_slug_available(
    session: AsyncSession,
    slug: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(Plant.id).where(Plant.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(Plant.id != exclude_id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise SlugConflictError(f"Plant with slug '{slug}' already exists")


async def _ensure_sku_available(
    session: AsyncSession,
    sku: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(Plant.id).where(Plant.sku == sku)
    if exclude_id is not None:
        stmt = stmt.where(Plant.id != exclude_id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise SkuConflictError(f"Plant with SKU '{sku}' already exists")


def _apply_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    category_id: uuid.UUID | None,
    is_active: bool | None,
    is_featured: bool | None,
    min_price: Decimal | None,
    max_price: Decimal | None,
) -> Select[Any]:
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Plant.name.ilike(pattern), Plant.sku.ilike(pattern)))
    if category_id is not None:
        stmt = stmt.where(Plant.category_id == category_id)
    if is_active is not None:
        stmt = stmt.where(Plant.is_active.is_(is_active))
    if is_featured is not None:
        stmt = stmt.where(Plant.is_featured.is_(is_featured))
    if min_price is not None:
        stmt = stmt.where(Plant.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Plant.price <= max_price)
    return stmt


async def list_plants(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    category_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    is_featured: bool | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: SortField = "created_at",
    order: SortOrder = "desc",
) -> tuple[list[Plant], int]:
    filters = {
        "search": search,
        "category_id": category_id,
        "is_active": is_active,
        "is_featured": is_featured,
        "min_price": min_price,
        "max_price": max_price,
    }

    count_stmt = _apply_filters(select(func.count()).select_from(Plant), **filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    column = _SORT_COLUMNS[sort]
    ordering = column.asc() if order == "asc" else column.desc()

    stmt = _apply_filters(select(Plant), **filters)
    stmt = (
        stmt.options(*_list_options())
        .order_by(ordering, Plant.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_plant(session: AsyncSession, plant_id: uuid.UUID) -> Plant:
    result = await session.execute(
        select(Plant).where(Plant.id == plant_id).options(*_detail_options())
    )
    plant = result.scalar_one_or_none()
    if plant is None:
        raise PlantNotFoundError("Plant not found")
    return plant


async def get_plant_by_slug(
    session: AsyncSession,
    slug: str,
    *,
    active_only: bool = False,
) -> Plant:
    stmt = select(Plant).where(Plant.slug == slug).options(*_detail_options())
    if active_only:
        stmt = stmt.where(Plant.is_active.is_(True))
    result = await session.execute(stmt)
    plant = result.scalar_one_or_none()
    if plant is None:
        raise PlantNotFoundError("Plant not found")
    return plant


async def create_plant(
    session: AsyncSession,
    *,
    category_id: uuid.UUID,
    name: str,
    name_vi: str | None,
    slug: str,
    description: str | None,
    description_vi: str | None,
    price: Decimal,
    price_vi: Decimal | None,
    stock: int,
    sku: str,
    is_featured: bool,
    is_active: bool,
) -> Plant:
    await get_category(session, category_id)
    await _ensure_slug_available(session, slug)
    await _ensure_sku_available(session, sku)

    plant = Plant(
        category_id=category_id,
        name=name,
        name_vi=name_vi,
        slug=slug,
        description=description,
        description_vi=description_vi,
        price=price,
        price_vi=price_vi,
        stock=stock,
        sku=sku,
        is_featured=is_featured,
        is_active=is_active,
    )
    session.add(plant)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_plant(session, plant.id)


async def update_plant(
    session: AsyncSession,
    plant_id: uuid.UUID,
    *,
    category_id: uuid.UUID | None = None,
    name: str | None = None,
    name_vi: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    description_vi: str | None = None,
    price: Decimal | None = None,
    price_vi: Decimal | None = None,
    stock: int | None = None,
    sku: str | None = None,
    is_featured: bool | None = None,
    is_active: bool | None = None,
    name_vi_provided: bool = False,
    description_provided: bool = False,
    description_vi_provided: bool = False,
    price_vi_provided: bool = False,
) -> Plant:
    plant = await get_plant(session, plant_id)

    if category_id is not None and category_id != plant.category_id:
        await get_category(session, category_id)
        plant.category_id = category_id

    if slug is not None and slug != plant.slug:
        await _ensure_slug_available(session, slug, exclude_id=plant.id)
        plant.slug = slug

    if sku is not None and sku != plant.sku:
        await _ensure_sku_available(session, sku, exclude_id=plant.id)
        plant.sku = sku

    if name is not None:
        plant.name = name
    if name_vi_provided:
        plant.name_vi = name_vi
    if description_provided:
        plant.description = description
    if description_vi_provided:
        plant.description_vi = description_vi
    if price is not None:
        plant.price = price
    if price_vi_provided:
        plant.price_vi = price_vi
    if stock is not None:
        plant.stock = stock
    if is_featured is not None:
        plant.is_featured = is_featured
    if is_active is not None:
        plant.is_active = is_active

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_plant(session, plant.id)


async def set_plant_status(
    session: AsyncSession,
    plant_id: uuid.UUID,
    *,
    is_active: bool,
) -> Plant:
    plant = await get_plant(session, plant_id)
    plant.is_active = is_active
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_plant(session, plant.id)


async def _ensure_plant_exists(session: AsyncSession, plant_id: uuid.UUID) -> None:
    result = await session.execute(select(Plant.id).where(Plant.id == plant_id))
    if result.scalar_one_or_none() is None:
        raise PlantNotFoundError("Plant not found")


async def list_plant_images(
    session: AsyncSession,
    plant_id: uuid.UUID,
) -> list[PlantImage]:
    await _ensure_plant_exists(session, plant_id)
    result = await session.execute(
        select(PlantImage)
        .where(PlantImage.plant_id == plant_id)
        .options(noload(PlantImage.plant))
        .order_by(PlantImage.sort_order, PlantImage.created_at)
    )
    return list(result.scalars().all())


async def _get_plant_image(
    session: AsyncSession,
    plant_id: uuid.UUID,
    image_id: uuid.UUID,
) -> PlantImage:
    await _ensure_plant_exists(session, plant_id)
    result = await session.execute(
        select(PlantImage)
        .where(PlantImage.id == image_id, PlantImage.plant_id == plant_id)
        .options(noload(PlantImage.plant))
    )
    image = result.scalar_one_or_none()
    if image is None:
        raise PlantImageNotFoundError("Image not found for this plant")
    return image


async def add_plant_image(
    session: AsyncSession,
    plant_id: uuid.UUID,
    *,
    url: str,
    type: PlantImageType,
    alt_text: str | None,
    sort_order: int,
) -> PlantImage:
    await _ensure_plant_exists(session, plant_id)
    image = PlantImage(
        plant_id=plant_id,
        url=url,
        type=type,
        alt_text=alt_text,
        sort_order=sort_order,
    )
    session.add(image)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(image)
    return image


async def update_plant_image(
    session: AsyncSession,
    plant_id: uuid.UUID,
    image_id: uuid.UUID,
    *,
    url: str | None = None,
    type: PlantImageType | None = None,
    alt_text: str | None = None,
    sort_order: int | None = None,
    alt_text_provided: bool = False,
) -> PlantImage:
    image = await _get_plant_image(session, plant_id, image_id)

    if url is not None:
        image.url = url
    if type is not None:
        image.type = type
    if alt_text_provided:
        image.alt_text = alt_text
    if sort_order is not None:
        image.sort_order = sort_order

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(image)
    return image


async def delete_plant_image(
    session: AsyncSession,
    plant_id: uuid.UUID,
    image_id: uuid.UUID,
) -> None:
    image = await _get_plant_image(session, plant_id, image_id)
    await session.delete(image)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def list_plant_pot_sizes(
    session: AsyncSession,
    plant_id: uuid.UUID,
) -> list[PlantPotSize]:
    await _ensure_plant_exists(session, plant_id)
    result = await session.execute(
        select(PlantPotSize)
        .where(PlantPotSize.plant_id == plant_id)
        .options(noload(PlantPotSize.plant))
        .order_by(PlantPotSize.sort_order, PlantPotSize.name)
    )
    return list(result.scalars().all())


async def _get_plant_pot_size(
    session: AsyncSession,
    plant_id: uuid.UUID,
    size_id: uuid.UUID,
) -> PlantPotSize:
    await _ensure_plant_exists(session, plant_id)
    result = await session.execute(
        select(PlantPotSize)
        .where(PlantPotSize.id == size_id, PlantPotSize.plant_id == plant_id)
        .options(noload(PlantPotSize.plant))
    )
    pot_size = result.scalar_one_or_none()
    if pot_size is None:
        raise PlantPotSizeNotFoundError("Pot size not found for this plant")
    return pot_size


async def add_plant_pot_size(
    session: AsyncSession,
    plant_id: uuid.UUID,
    *,
    name: str,
    price_adjustment: Decimal,
    price_adjustment_vi: Decimal | None,
    sort_order: int,
    is_active: bool,
) -> PlantPotSize:
    await _ensure_plant_exists(session, plant_id)
    pot_size = PlantPotSize(
        plant_id=plant_id,
        name=name,
        price_adjustment=price_adjustment,
        price_adjustment_vi=price_adjustment_vi,
        sort_order=sort_order,
        is_active=is_active,
    )
    session.add(pot_size)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(pot_size)
    return pot_size


async def update_plant_pot_size(
    session: AsyncSession,
    plant_id: uuid.UUID,
    size_id: uuid.UUID,
    *,
    name: str | None = None,
    price_adjustment: Decimal | None = None,
    price_adjustment_vi: Decimal | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
    price_adjustment_vi_provided: bool = False,
) -> PlantPotSize:
    pot_size = await _get_plant_pot_size(session, plant_id, size_id)

    if name is not None:
        pot_size.name = name
    if price_adjustment is not None:
        pot_size.price_adjustment = price_adjustment
    if price_adjustment_vi_provided:
        pot_size.price_adjustment_vi = price_adjustment_vi
    if sort_order is not None:
        pot_size.sort_order = sort_order
    if is_active is not None:
        pot_size.is_active = is_active

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(pot_size)
    return pot_size


async def delete_plant_pot_size(
    session: AsyncSession,
    plant_id: uuid.UUID,
    size_id: uuid.UUID,
) -> None:
    pot_size = await _get_plant_pot_size(session, plant_id, size_id)
    await session.delete(pot_size)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
