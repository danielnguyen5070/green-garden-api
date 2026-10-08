"""Public storefront plant routes. No authentication; only active plants are exposed."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.text import normalize_slug
from app.features.plants.models import Plant
from app.features.plants.schemas import (
    PlantImageResponse,
    PlantPotSizeResponse,
    PublicPlantDetail,
    PublicPlantImage,
    PublicPlantListItem,
    PublicPlantListResponse,
    PublicPlantSearchResponse,
    PublicPotSizeSummary,
)
from app.features.plants.service import (
    SearchLocale,
    SortField,
    SortOrder,
    active_pot_sizes,
    get_plant_by_slug,
    list_plants,
    search_plants,
    sorted_images,
)

router = APIRouter(prefix="/storefront", tags=["storefront"])


def _public_list_item(plant: Plant) -> PublicPlantListItem:
    pot_sizes = active_pot_sizes(plant)
    return PublicPlantListItem(
        id=plant.id,
        name=plant.name,
        name_vi=plant.name_vi,
        slug=plant.slug,
        description=plant.description,
        description_vi=plant.description_vi,
        og_image_url=plant.og_image_url,
        price=plant.price,
        price_vi=plant.price_vi,
        stock=plant.stock,
        is_featured=plant.is_featured,
        category=plant.category,
        images=[PublicPlantImage.model_validate(image) for image in sorted_images(plant)],
        default_pot_size=(
            PublicPotSizeSummary.model_validate(pot_sizes[0]) if pot_sizes else None
        ),
        updated_at=plant.updated_at,
    )


@router.get(
    "/plants",
    response_model=PublicPlantListResponse,
    summary="List active plants (public)",
    description=(
        "Paginated storefront catalogue. Inactive plants are never returned.\n\n"
        "Each row carries everything a catalogue card needs — English and "
        "Vietnamese copy (`name` / `name_vi`, `description` / `description_vi`, "
        "one shared `slug`), the VND selling price `price_vi` (the legacy "
        "`price` is never charged), `stock`, `is_featured`, the category "
        "summary, the plant's media ordered by `sort_order` ascending, and "
        "`default_pot_size` — the pot size checkout uses when none is chosen — "
        "so the frontend never has to call the detail endpoint per card. Images "
        "and pot sizes are loaded with one extra query each for the whole page."
    ),
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
        with_images=True,
    )
    return PublicPlantListResponse(
        items=[_public_list_item(plant) for plant in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/plants/search",
    response_model=PublicPlantSearchResponse,
    summary="Search active plants (public)",
    description=(
        "Keyword search over the active storefront catalogue. Matching is "
        "partial and case-insensitive; LIKE metacharacters in `q` are treated "
        "literally.\n\n"
        "`locale` selects which copy columns to search: `en` matches `name` / "
        "`description`, `vi` matches `name_vi` / `description_vi`. An empty or "
        "whitespace-only `q` returns zero results rather than the full "
        "catalogue. Results are capped by `limit` (default 20, max 100)."
    ),
)
async def search_public_plants(
    q: str = Query(default="", max_length=255, description="Search keyword"),
    locale: SearchLocale = Query(
        default="vi",
        description="Which locale fields to search (`vi` or `en`)",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PublicPlantSearchResponse:
    """Locale-aware storefront search. Inactive plants are never returned."""
    query, items, total = await search_plants(
        db,
        query=q,
        locale=locale,
        limit=limit,
    )
    return PublicPlantSearchResponse(
        query=query,
        total=total,
        items=[_public_list_item(plant) for plant in items],
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
    plant = await get_plant_by_slug(db, normalize_slug(slug), active_only=True)

    return PublicPlantDetail(
        id=plant.id,
        name=plant.name,
        name_vi=plant.name_vi,
        slug=plant.slug,
        description=plant.description,
        description_vi=plant.description_vi,
        long_description=plant.long_description,
        long_description_vi=plant.long_description_vi,
        og_image_url=plant.og_image_url,
        price=plant.price,
        price_vi=plant.price_vi,
        is_featured=plant.is_featured,
        in_stock=plant.stock > 0,
        plant_type=plant.plant_type,
        difficulty=plant.difficulty,
        growth_rate=plant.growth_rate,
        sunlight=plant.sunlight,
        watering=plant.watering,
        space_requirement=plant.space_requirement,
        indoor_suitable=plant.indoor_suitable,
        outdoor_suitable=plant.outdoor_suitable,
        pet_safe=plant.pet_safe,
        beginner_friendly=plant.beginner_friendly,
        category=plant.category,
        images=[
            PlantImageResponse.model_validate(image)
            for image in sorted_images(plant)
        ],
        pot_sizes=[
            PlantPotSizeResponse.model_validate(size) for size in active_pot_sizes(plant)
        ],
    )
