"""Admin management API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.admin import Admin
from app.schemas.admin import (
    AdminCreate,
    AdminListResponse,
    AdminPasswordUpdate,
    AdminResponse,
    AdminStatusUpdate,
    AdminUpdate,
)
from app.schemas.auth import MessageResponse
from app.services.admin_service import (
    AdminNotFoundError,
    EmailConflictError,
    SelfDeactivationError,
    change_admin_password,
    create_admin_account,
    get_admin,
    list_admins,
    update_admin,
    update_admin_status,
)

router = APIRouter(prefix="/admins", tags=["admins"])


def _map_admin_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, AdminNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, EmailConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, SelfDeactivationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.get(
    "",
    response_model=AdminListResponse,
    summary="List admins",
)
async def get_admins(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: Admin = Depends(get_current_admin),
) -> AdminListResponse:
    items, total = await list_admins(db, page=page, page_size=page_size)
    return AdminListResponse(
        items=[AdminResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/{admin_id}",
    response_model=AdminResponse,
    summary="Get admin",
)
async def get_admin_by_id(
    admin_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: Admin = Depends(get_current_admin),
) -> AdminResponse:
    try:
        admin = await get_admin(db, admin_id)
    except AdminNotFoundError as exc:
        raise _map_admin_errors(exc) from exc
    return AdminResponse.model_validate(admin)


@router.post(
    "",
    response_model=AdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create admin",
)
async def create_admin(
    payload: AdminCreate,
    db: AsyncSession = Depends(get_db),
    _: Admin = Depends(get_current_admin),
) -> AdminResponse:
    try:
        admin = await create_admin_account(
            db,
            name=payload.name,
            email=payload.email,
            password=payload.password,
        )
    except EmailConflictError as exc:
        raise _map_admin_errors(exc) from exc
    return AdminResponse.model_validate(admin)


@router.patch(
    "/{admin_id}",
    response_model=AdminResponse,
    summary="Update admin",
)
async def patch_admin(
    admin_id: UUID,
    payload: AdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> AdminResponse:
    try:
        admin = await update_admin(
            db,
            admin_id,
            name=payload.name,
            email=str(payload.email) if payload.email is not None else None,
            is_active=payload.is_active,
            current_admin_id=current_admin.id,
        )
    except (AdminNotFoundError, EmailConflictError, SelfDeactivationError) as exc:
        raise _map_admin_errors(exc) from exc
    return AdminResponse.model_validate(admin)


@router.patch(
    "/{admin_id}/status",
    response_model=AdminResponse,
    summary="Update admin status",
)
async def patch_admin_status(
    admin_id: UUID,
    payload: AdminStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> AdminResponse:
    try:
        admin = await update_admin_status(
            db,
            admin_id,
            is_active=payload.is_active,
            current_admin_id=current_admin.id,
        )
    except (AdminNotFoundError, SelfDeactivationError) as exc:
        raise _map_admin_errors(exc) from exc
    return AdminResponse.model_validate(admin)


@router.patch(
    "/{admin_id}/password",
    response_model=MessageResponse,
    summary="Change admin password",
)
async def patch_admin_password(
    admin_id: UUID,
    payload: AdminPasswordUpdate,
    db: AsyncSession = Depends(get_db),
    _: Admin = Depends(get_current_admin),
) -> MessageResponse:
    try:
        await change_admin_password(db, admin_id, password=payload.password)
    except AdminNotFoundError as exc:
        raise _map_admin_errors(exc) from exc
    return MessageResponse(message="Password updated successfully")
