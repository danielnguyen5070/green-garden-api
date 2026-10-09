"""Auth API routes.

`POST /login` is rate-limited per client IP and, for failed attempts, per email.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.cookies import clear_auth_cookies, set_access_cookie, set_auth_cookies
from app.core.database import get_db
from app.core.rate_limit import (
    RATE_LIMITED_RESPONSES,
    ensure_login_email_allowed,
    login_limit,
    rate_limit,
    record_login_email_failure,
    refresh_limit,
)
from app.core.security import create_token
from app.features.admins.models import Admin
from app.features.admins.schemas import AdminResponse
from app.features.auth.dependencies import get_current_admin
from app.features.auth.schemas import (
    AdminLoginRequest,
    AuthResponse,
    MessageResponse,
)
from app.features.auth.service import (
    AuthenticationError,
    InvalidCredentialsError,
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
    responses=RATE_LIMITED_RESPONSES,
)
@rate_limit(login_limit)
async def login(
    request: Request,
    payload: AdminLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Authenticate an admin and set HttpOnly access + refresh cookies.

    Tokens are never returned in the JSON body.
    """
    ensure_login_email_allowed(payload.email)
    try:
        admin = await authenticate_admin(
            db,
            email=payload.email,
            password=payload.password,
        )
    except InvalidCredentialsError:
        record_login_email_failure(payload.email)
        raise

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
    responses=RATE_LIMITED_RESPONSES,
)
@rate_limit(refresh_limit)
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
        raise AuthenticationError(log_detail="Missing refresh cookie")

    admin = await resolve_admin_from_token(
        db,
        token=refresh_token,
        expected_type="refresh",
    )

    access_token = create_token(subject=admin.id, token_type="access")
    set_access_cookie(response, access_token=access_token)

    return MessageResponse(message="Token refreshed")
