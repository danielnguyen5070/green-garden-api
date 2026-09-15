"""Admin management API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.admin import Admin


AUTH_PREFIX = "/api/v1/auth"
ADMINS_PREFIX = "/api/v1/admins"


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _assert_no_secrets(payload: dict) -> None:
    text = str(payload)
    assert "password_hash" not in text
    assert "password" not in payload
    assert "access_token" not in text
    assert "refresh_token" not in text


@pytest.mark.asyncio
async def test_list_admins_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(ADMINS_PREFIX)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_admin_success(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    email = f"new-admin-{uuid4().hex[:8]}@example.com"
    response = await client.post(
        ADMINS_PREFIX,
        json={
            "name": "Nguyen Van A",
            "email": email,
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Nguyen Van A"
    assert body["email"] == email
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body
    _assert_no_secrets(body)

    result = await test_db_session.execute(select(Admin).where(Admin.email == email))
    stored = result.scalar_one()
    assert stored.password_hash != "StrongPassword123!"
    assert stored.password_hash.startswith("$argon2")
    assert verify_password("StrongPassword123!", stored.password_hash)


@pytest.mark.asyncio
async def test_create_admin_duplicate_email(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        ADMINS_PREFIX,
        json={
            "name": "Duplicate",
            "email": active_admin.email,
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_admins(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{ADMINS_PREFIX}?page=1&page_size=20")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] >= 1
    assert isinstance(body["items"], list)
    assert any(item["id"] == str(active_admin.id) for item in body["items"])
    for item in body["items"]:
        _assert_no_secrets(item)


@pytest.mark.asyncio
async def test_get_admin(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{ADMINS_PREFIX}/{active_admin.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(active_admin.id)
    assert body["email"] == active_admin.email
    _assert_no_secrets(body)


@pytest.mark.asyncio
async def test_get_admin_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    missing_id = uuid4()
    response = await client.get(f"{ADMINS_PREFIX}/{missing_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_admin(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    other = Admin(
        name="Other Admin",
        email=f"other-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct-password"),
        is_active=True,
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    new_email = f"updated-{uuid4().hex[:8]}@example.com"
    response = await client.patch(
        f"{ADMINS_PREFIX}/{other.id}",
        json={"name": "Updated Name", "email": new_email},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated Name"
    assert body["email"] == new_email
    _assert_no_secrets(body)


@pytest.mark.asyncio
async def test_update_admin_duplicate_email(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    other = Admin(
        name="Other Admin",
        email=f"other-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct-password"),
        is_active=True,
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    response = await client.patch(
        f"{ADMINS_PREFIX}/{other.id}",
        json={"email": active_admin.email},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_change_admin_password(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    other = Admin(
        name="Password Target",
        email=f"pwd-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct-password"),
        is_active=True,
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    response = await client.patch(
        f"{ADMINS_PREFIX}/{other.id}/password",
        json={"password": "NewStrongPassword123!"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Password updated successfully"

    await test_db_session.refresh(other)
    result = await test_db_session.execute(select(Admin).where(Admin.id == other.id))
    stored = result.scalar_one()
    assert stored.password_hash.startswith("$argon2")
    assert verify_password("NewStrongPassword123!", stored.password_hash)
    assert not verify_password("correct-password", stored.password_hash)


@pytest.mark.asyncio
async def test_deactivate_and_activate_admin(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    other = Admin(
        name="Status Target",
        email=f"status-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct-password"),
        is_active=True,
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    deactivate = await client.patch(
        f"{ADMINS_PREFIX}/{other.id}/status",
        json={"is_active": False},
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False
    _assert_no_secrets(deactivate.json())

    activate = await client.patch(
        f"{ADMINS_PREFIX}/{other.id}/status",
        json={"is_active": True},
    )
    assert activate.status_code == 200
    assert activate.json()["is_active"] is True


@pytest.mark.asyncio
async def test_cannot_deactivate_self(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(
        f"{ADMINS_PREFIX}/{active_admin.id}/status",
        json={"is_active": False},
    )
    assert response.status_code == 400
    assert "own account" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_password_hash_never_returned_on_admin_endpoints(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    create = await client.post(
        ADMINS_PREFIX,
        json={
            "name": "Secret Check",
            "email": f"secret-{uuid4().hex[:8]}@example.com",
            "password": "StrongPassword123!",
        },
    )
    listed = await client.get(ADMINS_PREFIX)
    detail = await client.get(f"{ADMINS_PREFIX}/{active_admin.id}")
    for payload in (create.json(), listed.json(), detail.json()):
        _assert_no_secrets(payload if isinstance(payload, dict) else {})
        if "items" in payload:
            for item in payload["items"]:
                _assert_no_secrets(item)
