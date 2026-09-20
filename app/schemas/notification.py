"""Notification request/response schemas (admin inbox)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType

__all__ = [
    "NotificationListResponse",
    "NotificationReadAllResponse",
    "NotificationResponse",
]


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: NotificationType
    title: str
    message: str
    entity_id: UUID | None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    page: int
    page_size: int
    total: int


class NotificationReadAllResponse(BaseModel):
    updated: int
