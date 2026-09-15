"""FastAPI dependencies for authentication."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.admin import Admin
from app.services.auth_service import AuthenticationError, resolve_admin_from_token


async def get_current_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Admin:
    """
    Read the access token from the HttpOnly cookie, validate JWT,
    and return an active Admin. Reuse this for all protected admin routes.
    """
    settings = get_settings()
    token = request.cookies.get(settings.auth_access_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    try:
        return await resolve_admin_from_token(
            db,
            token=token,
            expected_type="access",
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
