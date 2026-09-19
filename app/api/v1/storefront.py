"""Public storefront routes: the catalogue and the cash-on-delivery checkout.

No authentication anywhere here. Only active plants are exposed, and checkout
reuses `app.services.order_service` — the same validation, snapshots and stock
movements as the admin panel, priced from the Vietnamese catalogue columns and
with the storefront shipping fee on top.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.text import normalize_slug
from app.models.plant import Plant
from app.models.plant_image import PlantImage
from app.schemas.category import (
    PublicCategoryListItem,
    PublicCategoryListResponse,
)
from app.schemas.plant import (
    PublicPlantDetail,
    PublicPlantListItem,
    PublicPlantListResponse,
)
from app.schemas.order import StorefrontOrderCreate, StorefrontOrderResponse
from app.schemas.plant_image import PlantImageResponse, PublicPlantImage
from app.schemas.plant_pot_size import PlantPotSizeResponse
from app.services.category_service import list_categories
from app.services.customer_service import CustomerInactiveError
from app.services.order_service import (
    InsufficientStockError,
    OrderItemInput,
    OrderPricing,
    OrderTotalTooLargeError,
    PlantUnavailableError,
    PotSizeUnavailableError,
    create_order,
)
from app.services.plant_service import (
    PlantNotFoundError,
    SortField,
    SortOrder,
    get_plant_by_slug,
    list_plants,
)

router = APIRouter(prefix="/storefront", tags=["storefront"])


def _sorted_images(plant: Plant) -> list[PlantImage]:
    """Media in display order: `sort_order` first, oldest first on a tie."""
    return sorted(plant.images, key=lambda image: (image.sort_order, image.created_at))


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
    description=(
        "Paginated storefront catalogue. Inactive plants are never returned.\n\n"
        "Each row carries everything a catalogue card needs — English and "
        "Vietnamese copy (`name` / `name_vi`, `description` / `description_vi`, "
        "`price` / `price_vi`, one shared `slug`), `stock`, `is_featured`, the "
        "category summary and the plant's media, ordered by `sort_order` "
        "ascending — so the frontend never has to call the detail endpoint per "
        "card. Images are loaded with one extra query for the whole page."
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
        items=[
            PublicPlantListItem(
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
                images=[
                    PublicPlantImage.model_validate(image)
                    for image in _sorted_images(plant)
                ],
            )
            for plant in items
        ],
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
        name_vi=plant.name_vi,
        slug=plant.slug,
        description=plant.description,
        description_vi=plant.description_vi,
        og_image_url=plant.og_image_url,
        price=plant.price,
        price_vi=plant.price_vi,
        is_featured=plant.is_featured,
        in_stock=plant.stock > 0,
        category=plant.category,
        images=[
            PlantImageResponse.model_validate(image)
            for image in _sorted_images(plant)
        ],
        pot_sizes=[
            PlantPotSizeResponse.model_validate(size)
            for size in sorted(plant.pot_sizes, key=lambda s: (s.sort_order, s.name))
            if size.is_active
        ],
    )


@router.post(
    "/orders",
    response_model=StorefrontOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a public customer order",
    description=(
        "Public cash-on-delivery checkout. **No authentication**: shoppers have "
        "no account and never log in, and no payment information is collected "
        "or stored.\n\n"
        "The customer is identified by phone, normalized to the canonical "
        "Vietnamese form first (`+84901234567` and `84901234567` both become "
        "`0901234567`), so the same shopper is never duplicated. A known "
        "number reuses the existing customer (keeping the name already on "
        "file), an unknown one creates a customer.\n\n"
        "Everything is priced from the Vietnamese catalogue: item names come "
        "from `plants.name_vi` (falling back to `name`), unit prices from "
        "`plants.price_vi` plus the selected pot size's `price_adjustment_vi`. "
        "The subtotal is the sum of `unit_price × quantity`, shipping is "
        "50,000 VND unless the subtotal is above 500,000 VND, and "
        "`total_amount` is subtotal plus shipping — prices or totals in the "
        "request body are ignored.\n\n"
        "Customer, order, item snapshots and the stock deduction commit in one "
        "transaction with the plant rows locked, so a rejected line leaves no "
        "partial order and no stock movement behind. New orders start as "
        "`pending`; the shop moves them on from the admin panel."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Order total too large, or the customer is deactivated"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Plant or selected pot size does not exist"
        },
        status.HTTP_409_CONFLICT: {
            "description": (
                "Insufficient stock, or the plant is not on sale in the "
                "Vietnamese storefront"
            )
        },
    },
)
async def post_storefront_order(
    payload: StorefrontOrderCreate,
    db: AsyncSession = Depends(get_db),
) -> StorefrontOrderResponse:
    try:
        order = await create_order(
            db,
            customer_phone=payload.customer.phone,
            customer_name=payload.customer.name,
            customer_email=None,
            shipping_address=payload.shipping_address,
            note=payload.note,
            items=[
                OrderItemInput(
                    plant_id=item.plant_id,
                    quantity=item.quantity,
                    pot_size=item.pot_size,
                )
                for item in payload.items
            ],
            pricing=OrderPricing.STOREFRONT,
        )
    except (PlantNotFoundError, PotSizeUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (InsufficientStockError, PlantUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (CustomerInactiveError, OrderTotalTooLargeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return StorefrontOrderResponse.model_validate(order)
