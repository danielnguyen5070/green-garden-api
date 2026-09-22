"""Plant management API routes (admin only)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.schemas.plant import (
    PlantCreate,
    PlantListItem,
    PlantListResponse,
    PlantResponse,
    PlantStatusUpdate,
    PlantUpdate,
)
from app.schemas.plant_image import (
    PlantImageCreate,
    PlantImageResponse,
    PlantImageUpdate,
)
from app.schemas.plant_pot_size import (
    PlantPotSizeCreate,
    PlantPotSizeResponse,
    PlantPotSizeUpdate,
)
from app.services.plant_service import (
    CategoryNotFoundError,
    PlantImageNotFoundError,
    PlantNotFoundError,
    PlantPotSizeNotFoundError,
    SkuConflictError,
    SlugConflictError,
    SortField,
    SortOrder,
    add_plant_image,
    add_plant_pot_size,
    create_plant,
    delete_plant_image,
    delete_plant_pot_size,
    get_plant,
    list_plant_images,
    list_plant_pot_sizes,
    list_plants,
    set_plant_status,
    update_plant,
    update_plant_image,
    update_plant_pot_size,
)

router = APIRouter(
    prefix="/plants",
    tags=["plants"],
    dependencies=[Depends(get_current_admin)],
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)

_NOT_FOUND = {
    status.HTTP_404_NOT_FOUND: {
        "description": "Plant, category, image or pot size not found"
    }
}
_CONFLICT = {
    status.HTTP_409_CONFLICT: {"description": "Slug or SKU already used by another plant"}
}


def _map_plant_errors(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            PlantNotFoundError,
            CategoryNotFoundError,
            PlantImageNotFoundError,
            PlantPotSizeNotFoundError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (SlugConflictError, SkuConflictError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.get(
    "",
    response_model=PlantListResponse,
    summary="List plants",
)
async def get_plants(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, description="Match plant name or SKU"),
    category_id: UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    is_featured: bool | None = Query(default=None),
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    sort: SortField = Query(default="created_at"),
    order: SortOrder = Query(default="desc"),
    db: AsyncSession = Depends(get_db),
) -> PlantListResponse:
    """Paginated plant list for the admin dashboard (active and inactive)."""
    items, total = await list_plants(
        db,
        page=page,
        page_size=page_size,
        search=search,
        category_id=category_id,
        is_active=is_active,
        is_featured=is_featured,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        order=order,
    )
    return PlantListResponse(
        items=[PlantListItem.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/{plant_id}",
    response_model=PlantResponse,
    summary="Get plant detail",
    responses=_NOT_FOUND,
)
async def get_plant_detail(
    plant_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PlantResponse:
    """Full plant detail with category, images and pot sizes."""
    try:
        plant = await get_plant(db, plant_id)
    except PlantNotFoundError as exc:
        raise _map_plant_errors(exc) from exc
    return PlantResponse.model_validate(plant)


@router.post(
    "",
    response_model=PlantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create plant",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def post_plant(
    payload: PlantCreate,
    db: AsyncSession = Depends(get_db),
) -> PlantResponse:
    """Create a plant. Slug and SKU must be unique; category must exist."""
    try:
        plant = await create_plant(
            db,
            category_id=payload.category_id,
            name=payload.name,
            name_vi=payload.name_vi,
            slug=payload.slug,
            description=payload.description,
            description_vi=payload.description_vi,
            long_description=payload.long_description,
            long_description_vi=payload.long_description_vi,
            og_image_url=(
                str(payload.og_image_url) if payload.og_image_url is not None else None
            ),
            price=payload.price,
            price_vi=payload.price_vi,
            stock=payload.stock,
            sku=payload.sku,
            is_featured=payload.is_featured,
            is_active=payload.is_active,
            plant_type=payload.plant_type,
            difficulty=payload.difficulty,
            growth_rate=payload.growth_rate,
            sunlight=payload.sunlight,
            watering=payload.watering,
            space_requirement=payload.space_requirement,
            indoor_suitable=payload.indoor_suitable,
            outdoor_suitable=payload.outdoor_suitable,
            pet_safe=payload.pet_safe,
            beginner_friendly=payload.beginner_friendly,
        )
    except (CategoryNotFoundError, SlugConflictError, SkuConflictError) as exc:
        raise _map_plant_errors(exc) from exc
    return PlantResponse.model_validate(plant)


@router.patch(
    "/{plant_id}",
    response_model=PlantResponse,
    summary="Update plant",
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def patch_plant(
    plant_id: UUID,
    payload: PlantUpdate,
    db: AsyncSession = Depends(get_db),
) -> PlantResponse:
    """Partial update. Slug/SKU uniqueness and category existence are validated."""
    try:
        plant = await update_plant(
            db,
            plant_id,
            category_id=payload.category_id,
            name=payload.name,
            name_vi=payload.name_vi,
            slug=payload.slug,
            description=payload.description,
            description_vi=payload.description_vi,
            long_description=payload.long_description,
            long_description_vi=payload.long_description_vi,
            og_image_url=(
                str(payload.og_image_url) if payload.og_image_url is not None else None
            ),
            price=payload.price,
            price_vi=payload.price_vi,
            stock=payload.stock,
            sku=payload.sku,
            is_featured=payload.is_featured,
            is_active=payload.is_active,
            plant_type=payload.plant_type,
            difficulty=payload.difficulty,
            growth_rate=payload.growth_rate,
            sunlight=payload.sunlight,
            watering=payload.watering,
            space_requirement=payload.space_requirement,
            indoor_suitable=payload.indoor_suitable,
            outdoor_suitable=payload.outdoor_suitable,
            pet_safe=payload.pet_safe,
            beginner_friendly=payload.beginner_friendly,
            name_vi_provided="name_vi" in payload.model_fields_set,
            description_provided="description" in payload.model_fields_set,
            description_vi_provided="description_vi" in payload.model_fields_set,
            long_description_provided="long_description" in payload.model_fields_set,
            long_description_vi_provided=(
                "long_description_vi" in payload.model_fields_set
            ),
            og_image_url_provided="og_image_url" in payload.model_fields_set,
            price_vi_provided="price_vi" in payload.model_fields_set,
            plant_type_provided="plant_type" in payload.model_fields_set,
            difficulty_provided="difficulty" in payload.model_fields_set,
            growth_rate_provided="growth_rate" in payload.model_fields_set,
            sunlight_provided="sunlight" in payload.model_fields_set,
            watering_provided="watering" in payload.model_fields_set,
            space_requirement_provided=(
                "space_requirement" in payload.model_fields_set
            ),
            indoor_suitable_provided="indoor_suitable" in payload.model_fields_set,
            outdoor_suitable_provided="outdoor_suitable" in payload.model_fields_set,
            pet_safe_provided="pet_safe" in payload.model_fields_set,
            beginner_friendly_provided=(
                "beginner_friendly" in payload.model_fields_set
            ),
        )
    except (
        PlantNotFoundError,
        CategoryNotFoundError,
        SlugConflictError,
        SkuConflictError,
    ) as exc:
        raise _map_plant_errors(exc) from exc
    return PlantResponse.model_validate(plant)


@router.patch(
    "/{plant_id}/status",
    response_model=PlantResponse,
    summary="Activate or deactivate plant",
    responses=_NOT_FOUND,
)
async def patch_plant_status(
    plant_id: UUID,
    payload: PlantStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> PlantResponse:
    """Soft enable/disable a plant. Inactive plants are hidden from the storefront."""
    try:
        plant = await set_plant_status(db, plant_id, is_active=payload.is_active)
    except PlantNotFoundError as exc:
        raise _map_plant_errors(exc) from exc
    return PlantResponse.model_validate(plant)


@router.get(
    "/{plant_id}/images",
    response_model=list[PlantImageResponse],
    summary="List plant images",
    responses=_NOT_FOUND,
)
async def get_plant_images(
    plant_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[PlantImageResponse]:
    """Media URLs for a plant, ordered by `sort_order`."""
    try:
        images = await list_plant_images(db, plant_id)
    except PlantNotFoundError as exc:
        raise _map_plant_errors(exc) from exc
    return [PlantImageResponse.model_validate(image) for image in images]


@router.post(
    "/{plant_id}/images",
    response_model=PlantImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add plant image",
    responses=_NOT_FOUND,
)
async def post_plant_image(
    plant_id: UUID,
    payload: PlantImageCreate,
    db: AsyncSession = Depends(get_db),
) -> PlantImageResponse:
    """Attach an external media URL. No binary upload is performed."""
    try:
        image = await add_plant_image(
            db,
            plant_id,
            url=str(payload.url),
            type=payload.type,
            alt_text=payload.alt_text,
            sort_order=payload.sort_order,
        )
    except PlantNotFoundError as exc:
        raise _map_plant_errors(exc) from exc
    return PlantImageResponse.model_validate(image)


@router.patch(
    "/{plant_id}/images/{image_id}",
    response_model=PlantImageResponse,
    summary="Update plant image",
    responses=_NOT_FOUND,
)
async def patch_plant_image(
    plant_id: UUID,
    image_id: UUID,
    payload: PlantImageUpdate,
    db: AsyncSession = Depends(get_db),
) -> PlantImageResponse:
    """Partial update of an image that must belong to the given plant."""
    try:
        image = await update_plant_image(
            db,
            plant_id,
            image_id,
            url=str(payload.url) if payload.url is not None else None,
            type=payload.type,
            alt_text=payload.alt_text,
            sort_order=payload.sort_order,
            alt_text_provided="alt_text" in payload.model_fields_set,
        )
    except (PlantNotFoundError, PlantImageNotFoundError) as exc:
        raise _map_plant_errors(exc) from exc
    return PlantImageResponse.model_validate(image)


@router.delete(
    "/{plant_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete plant image",
    responses=_NOT_FOUND,
)
async def remove_plant_image(
    plant_id: UUID,
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete only the image record; the plant is untouched."""
    try:
        await delete_plant_image(db, plant_id, image_id)
    except (PlantNotFoundError, PlantImageNotFoundError) as exc:
        raise _map_plant_errors(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{plant_id}/pot-sizes",
    response_model=list[PlantPotSizeResponse],
    summary="List plant pot sizes",
    responses=_NOT_FOUND,
)
async def get_plant_pot_sizes(
    plant_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[PlantPotSizeResponse]:
    """Pot size variants for a plant, ordered by `sort_order`."""
    try:
        pot_sizes = await list_plant_pot_sizes(db, plant_id)
    except PlantNotFoundError as exc:
        raise _map_plant_errors(exc) from exc
    return [PlantPotSizeResponse.model_validate(size) for size in pot_sizes]


@router.post(
    "/{plant_id}/pot-sizes",
    response_model=PlantPotSizeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add plant pot size",
    responses=_NOT_FOUND,
)
async def post_plant_pot_size(
    plant_id: UUID,
    payload: PlantPotSizeCreate,
    db: AsyncSession = Depends(get_db),
) -> PlantPotSizeResponse:
    """Create a pot size variant with a non-negative price adjustment."""
    try:
        pot_size = await add_plant_pot_size(
            db,
            plant_id,
            name=payload.name,
            price_adjustment=payload.price_adjustment,
            price_adjustment_vi=payload.price_adjustment_vi,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
    except PlantNotFoundError as exc:
        raise _map_plant_errors(exc) from exc
    return PlantPotSizeResponse.model_validate(pot_size)


@router.patch(
    "/{plant_id}/pot-sizes/{size_id}",
    response_model=PlantPotSizeResponse,
    summary="Update plant pot size",
    responses=_NOT_FOUND,
)
async def patch_plant_pot_size(
    plant_id: UUID,
    size_id: UUID,
    payload: PlantPotSizeUpdate,
    db: AsyncSession = Depends(get_db),
) -> PlantPotSizeResponse:
    """Partial update of a pot size that must belong to the given plant."""
    try:
        pot_size = await update_plant_pot_size(
            db,
            plant_id,
            size_id,
            name=payload.name,
            price_adjustment=payload.price_adjustment,
            price_adjustment_vi=payload.price_adjustment_vi,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
            price_adjustment_vi_provided=(
                "price_adjustment_vi" in payload.model_fields_set
            ),
        )
    except (PlantNotFoundError, PlantPotSizeNotFoundError) as exc:
        raise _map_plant_errors(exc) from exc
    return PlantPotSizeResponse.model_validate(pot_size)


@router.delete(
    "/{plant_id}/pot-sizes/{size_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete plant pot size",
    responses=_NOT_FOUND,
)
async def remove_plant_pot_size(
    plant_id: UUID,
    size_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete only the pot size record; the plant is untouched."""
    try:
        await delete_plant_pot_size(db, plant_id, size_id)
    except (PlantNotFoundError, PlantPotSizeNotFoundError) as exc:
        raise _map_plant_errors(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
