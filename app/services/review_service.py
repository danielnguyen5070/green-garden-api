"""Customer review business logic (website-wide shop reviews and plant reviews)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.plant import Plant
from app.models.review import Review, ReviewStatus
from app.services.storefront_notify import notify_storefront

ReviewScope = Literal["shop", "plant"]
"""`shop` = website-wide reviews (no plant); `plant` = reviews of any plant."""


class ReviewNotFoundError(Exception):
    """Raised when a review id does not exist."""


@dataclass
class ReviewSummary:
    average_rating: float = 0.0
    total_reviews: int = 0
    rating_distribution: dict[int, int] = field(
        default_factory=lambda: {star: 0 for star in range(1, 6)}
    )


def _with_plant_summary() -> Any:
    # Only the columns the summary needs; skip the plant's own eager loads.
    return (
        selectinload(Review.plant)
        .load_only(Plant.id, Plant.name, Plant.name_vi, Plant.slug)
        .raiseload("*")
    )


def _apply_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    status: ReviewStatus | None,
    plant_id: uuid.UUID | None,
    scope: ReviewScope | None,
) -> Select[Any]:
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Review.name.ilike(pattern), Review.content.ilike(pattern))
        )
    if status is not None:
        stmt = stmt.where(Review.status == status)
    if plant_id is not None:
        stmt = stmt.where(Review.plant_id == plant_id)
    if scope == "shop":
        stmt = stmt.where(Review.plant_id.is_(None))
    elif scope == "plant":
        stmt = stmt.where(Review.plant_id.is_not(None))
    return stmt


async def list_reviews(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    status: ReviewStatus | None = None,
    plant_id: uuid.UUID | None = None,
    scope: ReviewScope | None = None,
    with_plant: bool = False,
) -> tuple[list[Review], int]:
    """Ordered by `created_at` descending (newest first)."""
    filters = {
        "search": search,
        "status": status,
        "plant_id": plant_id,
        "scope": scope,
    }

    count_stmt = _apply_filters(select(func.count()).select_from(Review), **filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = _apply_filters(select(Review), **filters)
    stmt = (
        stmt.order_by(Review.created_at.desc(), Review.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if with_plant:
        stmt = stmt.options(_with_plant_summary())
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_review_summary(
    session: AsyncSession,
    *,
    plant_id: uuid.UUID | None = None,
    scope: ReviewScope | None = None,
) -> ReviewSummary:
    """Average, count, and 1-5 star distribution of approved reviews."""
    stmt = _apply_filters(
        select(Review.rating, func.count()).group_by(Review.rating),
        search=None,
        status=ReviewStatus.APPROVED,
        plant_id=plant_id,
        scope=scope,
    )
    rows = (await session.execute(stmt)).all()

    summary = ReviewSummary()
    rating_sum = 0
    for rating, count in rows:
        summary.rating_distribution[int(rating)] = int(count)
        summary.total_reviews += int(count)
        rating_sum += int(rating) * int(count)
    if summary.total_reviews:
        summary.average_rating = round(rating_sum / summary.total_reviews, 1)
    return summary


async def get_review(session: AsyncSession, review_id: uuid.UUID) -> Review:
    result = await session.execute(
        select(Review).where(Review.id == review_id).options(_with_plant_summary())
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise ReviewNotFoundError("Review not found")
    return review


async def create_review(
    session: AsyncSession,
    *,
    name: str,
    rating: int,
    content: str,
    plant_id: uuid.UUID | None = None,
) -> Review:
    """Public submission — always stored as `pending` until an admin moderates."""
    review = Review(
        name=name,
        rating=rating,
        content=content,
        status=ReviewStatus.PENDING,
        plant_id=plant_id,
    )
    session.add(review)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_review(session, review.id)


async def set_review_status(
    session: AsyncSession,
    review_id: uuid.UUID,
    *,
    status: ReviewStatus,
) -> Review:
    review = await get_review(session, review_id)
    review.status = status
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    review = await get_review(session, review.id)
    notify_storefront("reviews", [review.plant.slug if review.plant else None])
    return review
