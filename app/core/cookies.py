"""HttpOnly auth cookie helpers. Cookie flags come from Settings."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Response

from app.core.config import Settings, get_settings


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    _set_cookie(
        response,
        name=cfg.auth_access_cookie_name,
        value=access_token,
        max_age=int(timedelta(minutes=cfg.access_token_expire_minutes).total_seconds()),
        settings=cfg,
    )
    _set_cookie(
        response,
        name=cfg.auth_refresh_cookie_name,
        value=refresh_token,
        max_age=int(timedelta(days=cfg.refresh_token_expire_days).total_seconds()),
        settings=cfg,
    )


def set_access_cookie(
    response: Response,
    *,
    access_token: str,
    settings: Settings | None = None,
) -> None:
    """Update only the access cookie (used by refresh)."""
    cfg = settings or get_settings()
    _set_cookie(
        response,
        name=cfg.auth_access_cookie_name,
        value=access_token,
        max_age=int(timedelta(minutes=cfg.access_token_expire_minutes).total_seconds()),
        settings=cfg,
    )


def clear_auth_cookies(
    response: Response,
    *,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    _delete_cookie(response, name=cfg.auth_access_cookie_name, settings=cfg)
    _delete_cookie(response, name=cfg.auth_refresh_cookie_name, settings=cfg)


def _set_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    max_age: int,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=settings.auth_cookie_path,
        domain=settings.auth_cookie_domain,
    )


def _delete_cookie(
    response: Response,
    *,
    name: str,
    settings: Settings,
) -> None:
    response.delete_cookie(
        key=name,
        path=settings.auth_cookie_path,
        domain=settings.auth_cookie_domain,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
