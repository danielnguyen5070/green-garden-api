"""Auth API routes.

TODO(production): Rate-limit POST /login (per IP / email) before public exposure.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.cookies import clear_auth_cookies, set_access_cookie, set_auth_cookies
from app.core.database import get_db
from app.core.security import create_token
from app.dependencies.auth import get_current_admin
from app.models.admin import Admin
from app.schemas.auth import (
    AdminLoginRequest,
    AdminResponse,
    AuthResponse,
    MessageResponse,
)
from app.services.auth_service import (
    AuthenticationError,
    authenticate_admin,
    issue_token_pair,
    resolve_admin_from_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin login",
)
async def login(
    payload: AdminLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Authenticate an admin and set HttpOnly access + refresh cookies.

    Tokens are never returned in the JSON body.
    """
    try:
        admin = await authenticate_admin(
            db,
            email=payload.email,
            password=payload.password,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    access_token, refresh_token = issue_token_pair(admin)
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)

    return AuthResponse(admin=AdminResponse.model_validate(admin))


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Admin logout",
)
async def logout(response: Response) -> MessageResponse:
    """Clear auth cookies. Does not require a valid access token."""
    clear_auth_cookies(response)
    return MessageResponse(message="Logged out successfully")


@router.get(
    "/me",
    response_model=AdminResponse,
    summary="Current admin",
)
async def me(current_admin: Admin = Depends(get_current_admin)) -> AdminResponse:
    """Return the authenticated admin profile (no password fields)."""
    return AdminResponse.model_validate(current_admin)


@router.post(
    "/refresh",
    response_model=MessageResponse,
    summary="Refresh access token",
)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Validate the refresh cookie and issue a new access cookie.

    Structured so refresh-token rotation / sessions can be added later
    without changing this endpoint contract.
    """
    settings = get_settings()
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    try:
        admin = await resolve_admin_from_token(
            db,
            token=refresh_token,
            expected_type="refresh",
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    access_token = create_token(subject=admin.id, token_type="access")
    set_access_cookie(response, access_token=access_token)

    return MessageResponse(message="Token refreshed")
