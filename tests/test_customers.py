"""Customers API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.customer import Customer
from app.models.order import Order, OrderStatus


AUTH_PREFIX = "/api/v1/auth"
CUSTOMERS_PREFIX = "/api/v1/customers"


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _unique_phone() -> str:
    return f"09{uuid4().int % 100_000_000:08d}"


def _customer_payload(**overrides: object) -> dict:
    unique = uuid4().hex[:8]
    payload: dict = {
        "phone": _unique_phone(),
        "name": f"Nguyen Van {unique}",
        "email": f"customer-{unique}@example.com",
    }
    payload.update(overrides)
    return payload


async def _create_customer(client: AsyncClient, **overrides: object) -> dict:
    response = await client.post(CUSTOMERS_PREFIX, json=_customer_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_customer(session: AsyncSession, **overrides: object) -> Customer:
    unique = uuid4().hex[:8]
    values: dict = {
        "phone": _unique_phone(),
        "name": f"Seeded Customer {unique}",
        "email": f"seeded-{unique}@example.com",
        "is_active": True,
    }
    values.update(overrides)
    customer = Customer(**values)
    session.add(customer)
    await session.commit()
    await session.refresh(customer)
    return customer


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_customers_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(CUSTOMERS_PREFIX)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_customer_unauthenticated(client: AsyncClient) -> None:
    response = await client.post(CUSTOMERS_PREFIX, json=_customer_payload())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_customer_unauthenticated(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    customer = await _seed_customer(test_db_session)
    response = await client.get(f"{CUSTOMERS_PREFIX}/{customer.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_customer_unauthenticated(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    customer = await _seed_customer(test_db_session)
    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{customer.id}",
        json={"name": "Hijacked"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_customer_status_unauthenticated(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    customer = await _seed_customer(test_db_session)
    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{customer.id}/status",
        json={"is_active": False},
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_customer_success(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    payload = _customer_payload()
    response = await client.post(CUSTOMERS_PREFIX, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["phone"] == payload["phone"]
    assert body["name"] == payload["name"]
    assert body["email"] == payload["email"]
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_customer_without_email(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        CUSTOMERS_PREFIX,
        json={"phone": _unique_phone(), "name": "No Email"},
    )
    assert response.status_code == 201
    assert response.json()["email"] is None


@pytest.mark.asyncio
async def test_create_customer_normalizes_phone_and_email(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    phone = _unique_phone()
    spaced = f"  {phone[:4]} {phone[4:7]} {phone[7:]}  "

    body = await _create_customer(
        client,
        phone=spaced,
        name="  Nguyen Van A  ",
        email="  Customer@Example.COM  ",
    )
    assert body["phone"] == phone
    assert body["name"] == "Nguyen Van A"
    assert body["email"] == "customer@example.com"


@pytest.mark.asyncio
async def test_create_customer_duplicate_phone(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    existing = await _create_customer(client)

    response = await client.post(
        CUSTOMERS_PREFIX,
        json=_customer_payload(phone=existing["phone"]),
    )
    assert response.status_code == 409
    assert "phone" in response.json()["detail"]
    # Database internals never leak into the error message
    assert "customers_phone_key" not in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_customer_duplicate_phone_ignoring_spaces(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    existing = await _create_customer(client)
    phone = existing["phone"]

    response = await client.post(
        CUSTOMERS_PREFIX,
        json=_customer_payload(phone=f"{phone[:4]} {phone[4:]}"),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("phone", ["", "   ", "not-a-phone", "12"])
async def test_create_customer_invalid_phone(
    client: AsyncClient,
    active_admin: Admin,
    phone: str,
) -> None:
    await _login(client, active_admin)
    response = await client.post(CUSTOMERS_PREFIX, json=_customer_payload(phone=phone))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_customer_missing_phone(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(CUSTOMERS_PREFIX, json={"name": "No Phone"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_customer_invalid_email(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        CUSTOMERS_PREFIX,
        json=_customer_payload(email="not-an-email"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_customer_empty_name(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(CUSTOMERS_PREFIX, json=_customer_payload(name="   "))
    assert response.status_code == 422


# --------------------------------------------------------------------------
# List
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_customers_pagination(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    for index in range(3):
        await _seed_customer(test_db_session, name=f"Paged {marker} {index}")

    first = await client.get(
        CUSTOMERS_PREFIX,
        params={"search": marker, "page": 1, "page_size": 2},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2

    second = await client.get(
        CUSTOMERS_PREFIX,
        params={"search": marker, "page": 2, "page_size": 2},
    )
    assert len(second.json()["items"]) == 1


@pytest.mark.asyncio
async def test_list_customers_invalid_page_size(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(CUSTOMERS_PREFIX, params={"page_size": 500})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_customers_by_phone_name_and_email(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    target = await _seed_customer(
        test_db_session,
        name=f"Findable {marker}",
        email=f"findable-{marker}@example.com",
    )
    await _seed_customer(test_db_session)

    by_phone = await client.get(CUSTOMERS_PREFIX, params={"search": target.phone})
    assert [item["id"] for item in by_phone.json()["items"]] == [str(target.id)]

    by_name = await client.get(CUSTOMERS_PREFIX, params={"search": f"Findable {marker}"})
    assert [item["id"] for item in by_name.json()["items"]] == [str(target.id)]

    by_email = await client.get(
        CUSTOMERS_PREFIX,
        params={"search": f"findable-{marker}@example.com"},
    )
    assert [item["id"] for item in by_email.json()["items"]] == [str(target.id)]


@pytest.mark.asyncio
async def test_list_customers_active_filter(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    enabled = await _seed_customer(
        test_db_session,
        name=f"Filter {marker} on",
        is_active=True,
    )
    disabled = await _seed_customer(
        test_db_session,
        name=f"Filter {marker} off",
        is_active=False,
    )

    active_only = await client.get(
        CUSTOMERS_PREFIX,
        params={"search": marker, "is_active": "true"},
    )
    assert [item["id"] for item in active_only.json()["items"]] == [str(enabled.id)]

    inactive_only = await client.get(
        CUSTOMERS_PREFIX,
        params={"search": marker, "is_active": "false"},
    )
    assert [item["id"] for item in inactive_only.json()["items"]] == [str(disabled.id)]

    both = await client.get(CUSTOMERS_PREFIX, params={"search": marker})
    assert both.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_customers_newest_first(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    older = await _seed_customer(test_db_session, name=f"Order {marker} older")
    newer = await _seed_customer(test_db_session, name=f"Order {marker} newer")

    response = await client.get(CUSTOMERS_PREFIX, params={"search": marker})
    assert [item["id"] for item in response.json()["items"]] == [
        str(newer.id),
        str(older.id),
    ]


# --------------------------------------------------------------------------
# Get
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_customer(client: AsyncClient, active_admin: Admin) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    response = await client.get(f"{CUSTOMERS_PREFIX}/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["phone"] == created["phone"]


@pytest.mark.asyncio
async def test_get_inactive_customer_visible_to_admin(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session, is_active=False)

    response = await client.get(f"{CUSTOMERS_PREFIX}/{customer.id}")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_get_customer_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{CUSTOMERS_PREFIX}/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Customer not found"


@pytest.mark.asyncio
async def test_get_customer_invalid_uuid(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{CUSTOMERS_PREFIX}/not-a-uuid")
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Update
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_customer_success(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)
    new_phone = _unique_phone()

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}",
        json={
            "phone": new_phone,
            "name": "Renamed Customer",
            "email": "renamed@example.com",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == new_phone
    assert body["name"] == "Renamed Customer"
    assert body["email"] == "renamed@example.com"
    # Identity and audit fields are never rewritten
    assert body["id"] == created["id"]
    assert body["created_at"] == created["created_at"]


@pytest.mark.asyncio
async def test_update_customer_ignores_readonly_fields(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}",
        json={
            "id": str(uuid4()),
            "created_at": "2000-01-01T00:00:00Z",
            "name": "Only The Name Changes",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["created_at"] == created["created_at"]
    assert body["name"] == "Only The Name Changes"


@pytest.mark.asyncio
async def test_update_customer_clears_email(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}",
        json={"email": None},
    )
    assert response.status_code == 200
    assert response.json()["email"] is None
    assert response.json()["name"] == created["name"]


@pytest.mark.asyncio
async def test_update_customer_duplicate_phone(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    first = await _create_customer(client)
    second = await _create_customer(client)

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{second['id']}",
        json={"phone": first["phone"]},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_customer_same_phone_is_allowed(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}",
        json={"phone": created["phone"], "name": "Same Phone"},
    )
    assert response.status_code == 200
    assert response.json()["phone"] == created["phone"]


@pytest.mark.asyncio
async def test_update_customer_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{uuid4()}",
        json={"name": "Nope"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_customer_invalid_phone(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}",
        json={"phone": "nope"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_and_activate_customer(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    deactivated = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}/status",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    # Soft deactivation keeps every other field
    assert deactivated.json()["phone"] == created["phone"]
    assert deactivated.json()["name"] == created["name"]
    assert deactivated.json()["email"] == created["email"]

    activated = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}/status",
        json={"is_active": True},
    )
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True


@pytest.mark.asyncio
async def test_customer_status_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{uuid4()}/status",
        json={"is_active": False},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_customer_status_requires_boolean(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{created['id']}/status",
        json={"is_active": "maybe"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_deactivated_customer_keeps_order_history(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    """Deactivation must never delete the customer or their orders."""
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)
    order = Order(
        customer_id=customer.id,
        order_number=f"GG-TEST-{uuid4().hex[:12]}",
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("850000.00"),
        shipping_address="123 Nguyen Trai, District 1, HCMC",
    )
    test_db_session.add(order)
    await test_db_session.commit()

    response = await client.patch(
        f"{CUSTOMERS_PREFIX}/{customer.id}/status",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    still_there = await client.get(f"/api/v1/orders/{order.id}")
    assert still_there.status_code == 200
    body = still_there.json()
    assert body["customer"]["id"] == str(customer.id)
    assert body["status"] == "completed"
    assert body["total_amount"] == "850000.00"


@pytest.mark.asyncio
async def test_no_delete_endpoint_for_customers(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_customer(client)

    response = await client.delete(f"{CUSTOMERS_PREFIX}/{created['id']}")
    assert response.status_code == 405
