"""Public storefront category routes. No authentication."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.features.categories.schemas import (
    PublicCategoryListItem,
    PublicCategoryListResponse,
)
from app.features.categories.service import list_categories

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
