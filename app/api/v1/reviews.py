"""Review moderation API routes (admin only)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.review import ReviewStatus
from app.schemas.review import (
    ReviewListItem,
    ReviewListResponse,
    ReviewResponse,
    ReviewStatusUpdate,
)
from app.services.review_service import (
    ReviewNotFoundError,
    get_review,
    list_reviews,
    set_review_status,
)

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
    dependencies=[Depends(get_current_admin)],
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Review not found"}}


@router.get(
    "",
    response_model=ReviewListResponse,
    summary="List reviews",
    description=(
        "Paginated review moderation list. Filter by `status` "
        "(`pending` / `approved` / `rejected`) or search name/content. "
        "Ordered by `created_at` descending."
    ),
)
async def get_reviews(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(
        default=None,
        description="Match reviewer name or content",
    ),
    status_filter: ReviewStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> ReviewListResponse:
    items, total = await list_reviews(
        db,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )
    return ReviewListResponse(
        items=[ReviewListItem.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/{review_id}",
    response_model=ReviewResponse,
    summary="Get review",
    description="Return a single review by id, any moderation status.",
    responses=_NOT_FOUND,
)
async def get_review_detail(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    try:
        review = await get_review(db, review_id)
    except ReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return ReviewResponse.model_validate(review)


@router.patch(
    "/{review_id}/status",
    response_model=ReviewResponse,
    summary="Update review status",
    description=(
        "Approve or reject a review. Only `approved` reviews appear on the "
        "public storefront."
    ),
    responses=_NOT_FOUND,
)
async def patch_review_status(
    review_id: UUID,
    payload: ReviewStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    try:
        review = await set_review_status(db, review_id, status=payload.status)
    except ReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return ReviewResponse.model_validate(review)
