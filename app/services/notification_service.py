"""Admin notification inbox business logic."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType


class NotificationNotFoundError(Exception):
    """Raised when a notification id does not exist."""


def queue_new_order_notification(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    order_number: str,
    customer_name: str,
) -> Notification:
    """
    Stage a `new_order` notification on the current session.

    The caller owns the transaction — this does not commit.
    """
    notification = Notification(
        type=NotificationType.NEW_ORDER,
        title="New order",
        message=f"Order {order_number} from {customer_name}",
        entity_id=order_id,
        is_read=False,
    )
    session.add(notification)
    return notification


async def list_notifications(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    is_read: bool | None = None,
) -> tuple[list[Notification], int]:
    """Newest first."""
    filters = []
    if is_read is not None:
        filters.append(Notification.is_read.is_(is_read))

    count_stmt = select(func.count()).select_from(Notification)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = select(Notification)
    if filters:
        stmt = stmt.where(*filters)
    stmt = (
        stmt.order_by(Notification.created_at.desc(), Notification.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_notification(
    session: AsyncSession,
    notification_id: uuid.UUID,
) -> Notification:
    result = await session.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise NotificationNotFoundError("Notification not found")
    return notification


async def mark_notification_read(
    session: AsyncSession,
    notification_id: uuid.UUID,
) -> Notification:
    notification = await get_notification(session, notification_id)
    notification.is_read = True
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_notification(session, notification.id)


async def mark_all_notifications_read(session: AsyncSession) -> int:
    """Mark every unread notification as read. Returns how many rows changed."""
    stmt = (
        update(Notification)
        .where(Notification.is_read.is_(False))
        .values(is_read=True)
    )
    try:
        result = await session.execute(stmt)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return int(result.rowcount or 0)
