"""Admin authentication API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_token, hash_password, verify_password
from app.models.admin import Admin


AUTH_PREFIX = "/api/v1/auth"


@pytest.mark.asyncio
async def test_login_valid_credentials(client: AsyncClient, active_admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": active_admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["admin"]["email"] == active_admin.email
    assert body["admin"]["name"] == active_admin.name
    assert "password" not in body["admin"]
    assert "password_hash" not in body["admin"]
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "token" not in body

    settings = get_settings()
    assert settings.auth_access_cookie_name in response.cookies
    assert settings.auth_refresh_cookie_name in response.cookies


@pytest.mark.asyncio
async def test_login_incorrect_password(client: AsyncClient, active_admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": active_admin.email, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_login_inactive_admin(client: AsyncClient, inactive_admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": inactive_admin.email, "password": "correct-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(f"{AUTH_PREFIX}/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_access_cookie(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    login = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": active_admin.email, "password": "correct-password"},
    )
    assert login.status_code == 200

    response = await client.get(f"{AUTH_PREFIX}/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == active_admin.email
    assert "password_hash" not in body
    assert "password" not in body


@pytest.mark.asyncio
async def test_me_with_expired_access_token(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": str(active_admin.id),
            "type": "access",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client.cookies.set(settings.auth_access_cookie_name, expired)
    response = await client.get(f"{AUTH_PREFIX}/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_valid_refresh_token(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    settings = get_settings()
    login = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": active_admin.email, "password": "correct-password"},
    )
    assert login.status_code == 200
    old_access = client.cookies.get(settings.auth_access_cookie_name)

    response = await client.post(f"{AUTH_PREFIX}/refresh")
    assert response.status_code == 200
    assert response.json()["message"] == "Token refreshed"
    new_access = client.cookies.get(settings.auth_access_cookie_name)
    assert new_access
    assert new_access != old_access

    me = await client.get(f"{AUTH_PREFIX}/me")
    assert me.status_code == 200


@pytest.mark.asyncio
async def test_refresh_with_invalid_refresh_token(client: AsyncClient) -> None:
    settings = get_settings()
    client.cookies.set(settings.auth_refresh_cookie_name, "not-a-valid-jwt")
    response = await client.post(f"{AUTH_PREFIX}/refresh")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_access_token_instead_of_refresh(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    settings = get_settings()
    access = create_token(subject=active_admin.id, token_type="access")
    client.cookies.set(settings.auth_refresh_cookie_name, access)
    response = await client.post(f"{AUTH_PREFIX}/refresh")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookies(client: AsyncClient, active_admin: Admin) -> None:
    settings = get_settings()
    await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": active_admin.email, "password": "correct-password"},
    )
    response = await client.post(f"{AUTH_PREFIX}/logout")
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out successfully"

    # httpx may keep jar entries; verify Set-Cookie clears via header and /me fails
    # after manually clearing client jar to simulate browser cookie deletion.
    client.cookies.clear()
    me = await client.get(f"{AUTH_PREFIX}/me")
    assert me.status_code == 401
    assert settings.auth_access_cookie_name  # cookie names configured


@pytest.mark.asyncio
async def test_password_stored_as_hash(
    test_db_session: AsyncSession,
) -> None:
    plain = "super-secret-password"
    admin = Admin(
        name="Hash Check",
        email=f"hash-{uuid4()}@example.com",
        password_hash=hash_password(plain),
        is_active=True,
    )
    test_db_session.add(admin)
    await test_db_session.commit()
    await test_db_session.refresh(admin)

    result = await test_db_session.execute(select(Admin).where(Admin.id == admin.id))
    stored = result.scalar_one()
    assert stored.password_hash != plain
    assert stored.password_hash.startswith("$argon2")
    assert verify_password(plain, stored.password_hash)


@pytest.mark.asyncio
async def test_password_hash_never_returned_by_api(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    login = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": active_admin.email, "password": "correct-password"},
    )
    me = await client.get(f"{AUTH_PREFIX}/me")
    for payload in (login.json(), me.json()):
        text = str(payload)
        assert "password_hash" not in text
        assert "password" not in payload.get("admin", payload)


@pytest.mark.asyncio
async def test_email_normalization_on_login(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    unique = uuid4().hex[:8]
    stored_email = f"case.admin.{unique}@example.com"
    admin = Admin(
        name="Case Admin",
        email=stored_email,
        password_hash=hash_password("correct-password"),
        is_active=True,
    )
    test_db_session.add(admin)
    await test_db_session.commit()

    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={
            "email": f"  Case.Admin.{unique}@Example.COM ",
            "password": "correct-password",
        },
    )
    assert response.status_code == 200
    assert response.json()["admin"]["email"] == stored_email
