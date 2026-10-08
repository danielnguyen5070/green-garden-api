"""FastAPI dependencies for authentication."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.features.admins.models import Admin
from app.features.auth.service import AuthenticationError, resolve_admin_from_token


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
        raise AuthenticationError(log_detail="Missing access cookie")
    return await resolve_admin_from_token(
        db,
        token=token,
        expected_type="access",
    )
