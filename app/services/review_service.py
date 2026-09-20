"""Website-wide customer review business logic."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import Review, ReviewStatus


class ReviewNotFoundError(Exception):
    """Raised when a review id does not exist."""


def _apply_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    status: ReviewStatus | None,
) -> Select[Any]:
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Review.name.ilike(pattern), Review.content.ilike(pattern))
        )
    if status is not None:
        stmt = stmt.where(Review.status == status)
    return stmt


async def list_reviews(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    status: ReviewStatus | None = None,
) -> tuple[list[Review], int]:
    """Ordered by `created_at` descending (newest first)."""
    filters = {"search": search, "status": status}

    count_stmt = _apply_filters(select(func.count()).select_from(Review), **filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = _apply_filters(select(Review), **filters)
    stmt = (
        stmt.order_by(Review.created_at.desc(), Review.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_review(session: AsyncSession, review_id: uuid.UUID) -> Review:
    result = await session.execute(select(Review).where(Review.id == review_id))
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
) -> Review:
    """Public submission — always stored as `pending` until an admin moderates."""
    review = Review(
        name=name,
        rating=rating,
        content=content,
        status=ReviewStatus.PENDING,
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
    return await get_review(session, review.id)
