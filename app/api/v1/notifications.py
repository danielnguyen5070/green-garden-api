"""Notification inbox API routes (admin only)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.schemas.notification import (
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationResponse,
)
from app.services.notification_service import (
    NotificationNotFoundError,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(get_current_admin)],
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Notification not found"}}


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="List notifications",
    description=(
        "Paginated admin notification inbox, newest first. Optional "
        "`is_read` filter."
    ),
)
async def get_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_read: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    items, total = await list_notifications(
        db,
        page=page,
        page_size=page_size,
        is_read=is_read,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.patch(
    "/read-all",
    response_model=NotificationReadAllResponse,
    summary="Mark all notifications as read",
    description="Sets `is_read=true` on every unread notification.",
)
async def patch_notifications_read_all(
    db: AsyncSession = Depends(get_db),
) -> NotificationReadAllResponse:
    updated = await mark_all_notifications_read(db)
    return NotificationReadAllResponse(updated=updated)


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark a notification as read",
    responses=_NOT_FOUND,
)
async def patch_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    try:
        notification = await mark_notification_read(db, notification_id)
    except NotificationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return NotificationResponse.model_validate(notification)
