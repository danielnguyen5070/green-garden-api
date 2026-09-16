"""Public storefront routes. No authentication; only active plants are exposed."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.text import normalize_slug
from app.schemas.category import (
    PublicCategoryListItem,
    PublicCategoryListResponse,
)
from app.schemas.plant import (
    PublicPlantDetail,
    PublicPlantListItem,
    PublicPlantListResponse,
)
from app.schemas.plant_image import PlantImageResponse
from app.schemas.plant_pot_size import PlantPotSizeResponse
from app.services.category_service import list_categories
from app.services.plant_service import (
    PlantNotFoundError,
    SortField,
    SortOrder,
    get_plant_by_slug,
    list_plants,
)

router = APIRouter(prefix="/storefront", tags=["storefront"])


@router.get(
    "/categories",
    response_model=PublicCategoryListResponse,
    summary="List active categories (public)",
    description=(
        "Storefront category navigation. Inactive categories are never returned. "
        "Ordered by `sort_order` then `created_at`, both ascending."
    ),
)
async def get_public_categories(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, description="Match category name or slug"),
    db: AsyncSession = Depends(get_db),
) -> PublicCategoryListResponse:
    items, total = await list_categories(
        db,
        page=page,
        page_size=page_size,
        search=search,
        is_active=True,
    )
    return PublicCategoryListResponse(
        items=[PublicCategoryListItem.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/plants",
    response_model=PublicPlantListResponse,
    summary="List active plants (public)",
)
async def get_public_plants(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, description="Match plant name or SKU"),
    category_id: UUID | None = Query(default=None),
    is_featured: bool | None = Query(default=None),
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    sort: SortField = Query(default="created_at"),
    order: SortOrder = Query(default="desc"),
    db: AsyncSession = Depends(get_db),
) -> PublicPlantListResponse:
    """Paginated catalogue for the storefront. Inactive plants are never returned."""
    items, total = await list_plants(
        db,
        page=page,
        page_size=page_size,
        search=search,
        category_id=category_id,
        is_active=True,
        is_featured=is_featured,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        order=order,
    )
    return PublicPlantListResponse(
        items=[PublicPlantListItem.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/plants/{slug}",
    response_model=PublicPlantDetail,
    summary="Get active plant by slug (public)",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Plant not found or inactive"}
    },
)
async def get_public_plant_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> PublicPlantDetail:
    """Storefront detail by slug. Returns 404 for unknown or inactive plants."""
    try:
        plant = await get_plant_by_slug(db, normalize_slug(slug), active_only=True)
    except PlantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return PublicPlantDetail(
        id=plant.id,
        name=plant.name,
        slug=plant.slug,
        description=plant.description,
        price=plant.price,
        is_featured=plant.is_featured,
        in_stock=plant.stock > 0,
        category=plant.category,
        images=[
            PlantImageResponse.model_validate(image)
            for image in sorted(plant.images, key=lambda i: (i.sort_order, i.created_at))
        ],
        pot_sizes=[
            PlantPotSizeResponse.model_validate(size)
            for size in sorted(plant.pot_sizes, key=lambda s: (s.sort_order, s.name))
            if size.is_active
        ],
    )
