"""Admin notification inbox tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.category import Category
from app.models.notification import Notification, NotificationType
from app.models.plant import Plant


AUTH_PREFIX = "/api/v1/auth"
NOTIFICATIONS_PREFIX = "/api/v1/notifications"
ORDERS_PREFIX = "/api/v1/orders"
CHECKOUT_PATH = "/api/v1/storefront/orders"


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _unique_phone() -> str:
    return f"09{uuid4().int % 100_000_000:08d}"


async def _seed_vi_plant(
    session: AsyncSession,
    category: Category,
    **overrides: object,
) -> Plant:
    unique = uuid4().hex[:8]
    values: dict = {
        "category_id": category.id,
        "name": f"Monstera {unique}",
        "name_vi": f"Cây Trầu Bà {unique}",
        "slug": f"monstera-{unique}",
        "price": Decimal("411111.11"),
        "price_vi": Decimal("300000.00"),
        "stock": 20,
        "sku": f"MON-{unique}",
        "is_active": True,
    }
    values.update(overrides)
    plant = Plant(**values)
    session.add(plant)
    await session.commit()
    await session.refresh(plant)
    return plant


async def _seed_notification(
    session: AsyncSession,
    **overrides: object,
) -> Notification:
    values: dict = {
        "type": NotificationType.NEW_ORDER,
        "title": "New order",
        "message": f"Order GG-TEST-{uuid4().hex[:4]} from Tester",
        "entity_id": uuid4(),
        "is_read": False,
    }
    values.update(overrides)
    notification = Notification(**values)
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return notification


async def _checkout(client: AsyncClient, plant: Plant, **overrides: object):
    payload: dict = {
        "customer": {"phone": _unique_phone(), "name": "Nguyễn Văn A"},
        "shipping_address": "123 Nguyễn Huệ, Quận 1, TP.HCM",
        "items": [{"plant_id": str(plant.id), "quantity": 1}],
    }
    payload.update(overrides)
    return await client.post(CHECKOUT_PATH, json=payload)


# --------------------------------------------------------------------------
# Creation from storefront checkout
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storefront_checkout_creates_new_order_notification(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category)
    customer_name = f"Checkout Notif {uuid4().hex[:6]}"

    response = await _checkout(
        client,
        plant,
        customer={"phone": _unique_phone(), "name": customer_name},
    )
    assert response.status_code == 201, response.text
    order = response.json()

    await _login(client, active_admin)
    listed = await client.get(
        NOTIFICATIONS_PREFIX,
        params={"page_size": 100},
    )
    assert listed.status_code == 200
    match = next(
        (
            item
            for item in listed.json()["items"]
            if item["entity_id"] == order["id"]
        ),
        None,
    )
    assert match is not None
    assert match["type"] == "new_order"
    assert match["title"] == "New order"
    assert order["order_number"] in match["message"]
    assert customer_name in match["message"]
    assert match["is_read"] is False


@pytest.mark.asyncio
async def test_admin_order_does_not_create_notification(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category)
    await _login(client, active_admin)

    before = await client.get(NOTIFICATIONS_PREFIX, params={"page_size": 1})
    before_total = before.json()["total"]

    created = await client.post(
        ORDERS_PREFIX,
        json={
            "customer": {
                "phone": _unique_phone(),
                "name": "Admin Panel Customer",
                "email": f"admin-order-{uuid4().hex[:6]}@example.com",
            },
            "shipping_address": "123 Nguyen Trai, HCMC",
            "items": [{"plant_id": str(plant.id), "quantity": 1}],
        },
    )
    assert created.status_code == 201, created.text

    after = await client.get(NOTIFICATIONS_PREFIX, params={"page_size": 1})
    assert after.json()["total"] == before_total


# --------------------------------------------------------------------------
# Admin APIs
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_notifications_requires_auth(client: AsyncClient) -> None:
    response = await client.get(NOTIFICATIONS_PREFIX)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_notifications_newest_first(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    older = await _seed_notification(
        test_db_session,
        message=f"Older {marker}",
    )
    newer = await _seed_notification(
        test_db_session,
        message=f"Newer {marker}",
    )

    await _login(client, active_admin)
    response = await client.get(
        NOTIFICATIONS_PREFIX,
        params={"page_size": 100},
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids.index(str(newer.id)) < ids.index(str(older.id))


@pytest.mark.asyncio
async def test_mark_notification_read(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    notification = await _seed_notification(test_db_session, is_read=False)
    notification_id = str(notification.id)
    await _login(client, active_admin)

    response = await client.patch(f"{NOTIFICATIONS_PREFIX}/{notification_id}/read")
    assert response.status_code == 200
    assert response.json()["is_read"] is True
    assert response.json()["id"] == notification_id

    listed = await client.get(
        NOTIFICATIONS_PREFIX,
        params={"is_read": "true", "page_size": 100},
    )
    assert notification_id in [item["id"] for item in listed.json()["items"]]


@pytest.mark.asyncio
async def test_mark_notification_read_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(f"{NOTIFICATIONS_PREFIX}/{uuid4()}/read")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mark_all_notifications_read(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    first_id = str(
        (
            await _seed_notification(
                test_db_session,
                message=f"Unread A {marker}",
                is_read=False,
            )
        ).id
    )
    second_id = str(
        (
            await _seed_notification(
                test_db_session,
                message=f"Unread B {marker}",
                is_read=False,
            )
        ).id
    )
    already_id = str(
        (
            await _seed_notification(
                test_db_session,
                message=f"Already read {marker}",
                is_read=True,
            )
        ).id
    )

    await _login(client, active_admin)
    response = await client.patch(f"{NOTIFICATIONS_PREFIX}/read-all")
    assert response.status_code == 200
    assert response.json()["updated"] >= 2

    unread = await client.get(
        NOTIFICATIONS_PREFIX,
        params={"is_read": "false", "page_size": 100},
    )
    unread_ids = {item["id"] for item in unread.json()["items"]}
    assert first_id not in unread_ids
    assert second_id not in unread_ids

    read = await client.get(
        NOTIFICATIONS_PREFIX,
        params={"is_read": "true", "page_size": 100},
    )
    read_ids = {item["id"] for item in read.json()["items"]}
    assert {first_id, second_id, already_id} <= read_ids


@pytest.mark.asyncio
async def test_mark_all_requires_auth(client: AsyncClient) -> None:
    response = await client.patch(f"{NOTIFICATIONS_PREFIX}/read-all")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_can_filter_unread(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    unread = await _seed_notification(
        test_db_session,
        message=f"Filter unread {marker}",
        is_read=False,
    )
    await _seed_notification(
        test_db_session,
        message=f"Filter read {marker}",
        is_read=True,
    )

    await _login(client, active_admin)
    response = await client.get(
        NOTIFICATIONS_PREFIX,
        params={"is_read": "false", "page_size": 100},
    )
    assert response.status_code == 200
    items = [
        item
        for item in response.json()["items"]
        if marker in item["message"]
    ]
    assert [item["id"] for item in items] == [str(unread.id)]
    assert all(item["is_read"] is False for item in items)
