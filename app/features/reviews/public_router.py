"""Public storefront review routes: shop reviews and plant reviews. No authentication."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.features.plants.dependencies import (
    PLANT_NOT_FOUND_RESPONSES,
    get_active_plant_or_404,
)
from app.features.reviews.models import ReviewStatus
from app.features.reviews.schemas import (
    PublicReviewListItem,
    PublicReviewListResponse,
    ReviewCreate,
    ReviewResponse,
)
from app.features.reviews.service import (
    ReviewScope,
    create_review,
    get_review_summary,
    list_reviews,
)
from app.shared.bot_protection.http import BOT_REJECTED_RESPONSES
from app.shared.bot_protection.service import verify_bot_signals

router = APIRouter(prefix="/storefront", tags=["storefront"])


async def _public_review_page(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    plant_id: UUID | None = None,
    scope: ReviewScope | None = None,
) -> PublicReviewListResponse:
    items, total = await list_reviews(
        db,
        page=page,
        page_size=page_size,
        status=ReviewStatus.APPROVED,
        plant_id=plant_id,
        scope=scope,
    )
    summary = await get_review_summary(db, plant_id=plant_id, scope=scope)
    return PublicReviewListResponse(
        items=[PublicReviewListItem.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        average_rating=summary.average_rating,
        total_reviews=summary.total_reviews,
        rating_distribution=summary.rating_distribution,
    )


@router.get(
    "/reviews",
    response_model=PublicReviewListResponse,
    summary="List approved reviews (public)",
    description=(
        "Paginated website-wide customer reviews (plant reviews are excluded). "
        "Only `approved` reviews are returned, ordered by `created_at` "
        "descending, with the average rating and star distribution of all "
        "approved shop reviews."
    ),
)
async def get_public_reviews(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PublicReviewListResponse:
    return await _public_review_page(
        db, page=page, page_size=page_size, scope="shop"
    )


@router.post(
    "/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a review (public)",
    description=(
        "Submit a website-wide customer review without authentication. The "
        "review is stored as `pending` and does not appear publicly until an "
        "admin approves it.\n\n"
        "Bot protection: the hidden `website` field must be empty and "
        "`form_elapsed_ms` must be at least 3000, otherwise `403`."
    ),
    responses=BOT_REJECTED_RESPONSES,
)
async def post_public_review(
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    verify_bot_signals(payload)
    review = await create_review(
        db,
        name=payload.name,
        rating=payload.rating,
        content=payload.content,
    )
    return ReviewResponse.model_validate(review)


@router.get(
    "/plants/{slug}/reviews",
    response_model=PublicReviewListResponse,
    summary="List approved reviews of a plant (public)",
    description=(
        "Paginated approved reviews of one active plant, ordered by "
        "`created_at` descending, with the plant's average rating and star "
        "distribution. Old slugs resolve to the plant like the detail endpoint."
    ),
    responses=PLANT_NOT_FOUND_RESPONSES,
)
async def get_public_plant_reviews(
    slug: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PublicReviewListResponse:
    plant = await get_active_plant_or_404(db, slug)
    return await _public_review_page(
        db, page=page, page_size=page_size, plant_id=plant.id
    )


@router.post(
    "/plants/{slug}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a review of a plant (public)",
    description=(
        "Submit a review of one active plant without authentication. The "
        "review is stored as `pending` and does not appear publicly until an "
        "admin approves it.\n\n"
        "Bot protection: the hidden `website` field must be empty and "
        "`form_elapsed_ms` must be at least 3000, otherwise `403`."
    ),
    responses={**PLANT_NOT_FOUND_RESPONSES, **BOT_REJECTED_RESPONSES},
)
async def post_public_plant_review(
    slug: str,
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    verify_bot_signals(payload)
    plant = await get_active_plant_or_404(db, slug)
    review = await create_review(
        db,
        name=payload.name,
        rating=payload.rating,
        content=payload.content,
        plant_id=plant.id,
    )
    return ReviewResponse.model_validate(review)
