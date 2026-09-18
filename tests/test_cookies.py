"""Unit tests for HttpOnly auth cookie helpers (domain/path consistency)."""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings
from app.core.cookies import clear_auth_cookies, set_access_cookie, set_auth_cookies


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "jwt_secret_key": "test-secret",
        "auth_cookie_secure": True,
        "auth_cookie_samesite": "none",
        "auth_cookie_path": "/",
        "auth_cookie_domain": ".ngocnganbentre.vn",
        "auth_access_cookie_name": "gg_access_token",
        "auth_refresh_cookie_name": "gg_refresh_token",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _set_cookie_headers(response: Response) -> list[str]:
    return [
        value.decode("latin-1")
        for key, value in response.raw_headers
        if key.lower() == b"set-cookie"
    ]


def test_set_auth_cookies_uses_shared_domain_and_security_flags() -> None:
    settings = _settings()
    response = Response()
    set_auth_cookies(
        response,
        access_token="access-token",
        refresh_token="refresh-token",
        settings=settings,
    )

    headers = _set_cookie_headers(response)
    assert len(headers) == 2

    access = next(h for h in headers if h.startswith("gg_access_token="))
    refresh = next(h for h in headers if h.startswith("gg_refresh_token="))

    for header in (access, refresh):
        assert "Domain=.ngocnganbentre.vn" in header
        assert "Path=/" in header
        assert "HttpOnly" in header
        assert "Secure" in header
        assert "SameSite=none" in header


def test_set_access_cookie_uses_same_domain() -> None:
    settings = _settings()
    response = Response()
    set_access_cookie(response, access_token="new-access", settings=settings)

    headers = _set_cookie_headers(response)
    assert len(headers) == 1
    assert headers[0].startswith("gg_access_token=")
    assert "Domain=.ngocnganbentre.vn" in headers[0]
    assert "Path=/" in headers[0]


def test_clear_auth_cookies_uses_same_domain_and_path() -> None:
    settings = _settings()
    response = Response()
    clear_auth_cookies(response, settings=settings)

    headers = _set_cookie_headers(response)
    assert len(headers) == 2

    for header in headers:
        assert "Domain=.ngocnganbentre.vn" in header
        assert "Path=/" in header
        assert "Max-Age=0" in header or "max-age=0" in header.lower()
        assert "HttpOnly" in header
        assert "Secure" in header
        assert "SameSite=none" in header


def test_blank_auth_cookie_domain_becomes_host_only() -> None:
    settings = _settings(auth_cookie_domain="   ")
    assert settings.auth_cookie_domain is None

    response = Response()
    set_auth_cookies(
        response,
        access_token="access-token",
        refresh_token="refresh-token",
        settings=settings,
    )
    headers = _set_cookie_headers(response)
    assert all("Domain=" not in header for header in headers)
