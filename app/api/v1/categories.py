"""Category management API routes (admin only)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.schemas.category import (
    CategoryCreate,
    CategoryListItem,
    CategoryListResponse,
    CategoryResponse,
    CategoryStatusUpdate,
    CategoryUpdate,
)
from app.services.category_service import (
    CategoryNotFoundError,
    CategorySlugConflictError,
    create_category,
    get_category,
    list_categories,
    set_category_status,
    update_category,
)

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    dependencies=[Depends(get_current_admin)],
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Category not found"}}
_CONFLICT = {
    status.HTTP_409_CONFLICT: {"description": "Slug already used by another category"}
}


def _map_category_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, CategoryNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CategorySlugConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.get(
    "",
    response_model=CategoryListResponse,
    summary="List categories",
    description=(
        "Paginated category list for the admin dashboard, including inactive "
        "categories. Ordered by `sort_order` then `created_at`, both ascending."
    ),
)
async def get_categories(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, description="Match category name or slug"),
    is_active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> CategoryListResponse:
    items, total = await list_categories(
        db,
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
    )
    return CategoryListResponse(
        items=[CategoryListItem.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Get category",
    description="Return a single category by id, active or inactive.",
    responses=_NOT_FOUND,
)
async def get_category_detail(
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    try:
        category = await get_category(db, category_id)
    except CategoryNotFoundError as exc:
        raise _map_category_errors(exc) from exc
    return CategoryResponse.model_validate(category)


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create category",
    description="Create a category. The slug is normalized and must be unique.",
    responses=_CONFLICT,
)
async def post_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    try:
        category = await create_category(
            db,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            image_url=str(payload.image_url) if payload.image_url is not None else None,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
    except CategorySlugConflictError as exc:
        raise _map_category_errors(exc) from exc
    return CategoryResponse.model_validate(category)


@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Update category",
    description=(
        "Partial update. Changing the slug re-checks uniqueness. Deactivating a "
        "category leaves its plants intact."
    ),
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def patch_category(
    category_id: UUID,
    payload: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    try:
        category = await update_category(
            db,
            category_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            image_url=str(payload.image_url) if payload.image_url is not None else None,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
            description_provided="description" in payload.model_fields_set,
            image_url_provided="image_url" in payload.model_fields_set,
        )
    except (CategoryNotFoundError, CategorySlugConflictError) as exc:
        raise _map_category_errors(exc) from exc
    return CategoryResponse.model_validate(category)


@router.patch(
    "/{category_id}/status",
    response_model=CategoryResponse,
    summary="Activate or deactivate category",
    description=(
        "Soft enable/disable. Records are never deleted and plants keep their "
        "category, but inactive categories are hidden from the storefront."
    ),
    responses=_NOT_FOUND,
)
async def patch_category_status(
    category_id: UUID,
    payload: CategoryStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> CategoryResponse:
    try:
        category = await set_category_status(
            db,
            category_id,
            is_active=payload.is_active,
        )
    except CategoryNotFoundError as exc:
        raise _map_category_errors(exc) from exc
    return CategoryResponse.model_validate(category)
