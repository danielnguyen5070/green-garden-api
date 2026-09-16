"""Orders API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.category import Category
from app.models.customer import Customer
from app.models.plant import Plant
from app.models.plant_pot_size import PlantPotSize
from app.services.order_service import get_order, list_orders


AUTH_PREFIX = "/api/v1/auth"
CUSTOMERS_PREFIX = "/api/v1/customers"
ORDERS_PREFIX = "/api/v1/orders"
PLANTS_PREFIX = "/api/v1/plants"

ORDER_NUMBER_PATTERN = re.compile(r"^GG-\d{8}-\d{4}$")


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _unique_phone() -> str:
    return f"09{uuid4().int % 100_000_000:08d}"


async def _seed_plant(
    session: AsyncSession,
    category: Category,
    **overrides: object,
) -> Plant:
    unique = uuid4().hex[:8]
    values: dict = {
        "category_id": category.id,
        "name": f"Monstera Deliciosa {unique}",
        "slug": f"monstera-{unique}",
        "price": Decimal("300000.00"),
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


async def _seed_pot_size(
    session: AsyncSession,
    plant: Plant,
    **overrides: object,
) -> PlantPotSize:
    values: dict = {
        "plant_id": plant.id,
        "name": "Large",
        "price_adjustment": Decimal("100000.00"),
        "sort_order": 1,
        "is_active": True,
    }
    values.update(overrides)
    pot_size = PlantPotSize(**values)
    session.add(pot_size)
    await session.commit()
    await session.refresh(pot_size)
    return pot_size


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


def _order_payload(plant: Plant, **overrides: object) -> dict:
    unique = uuid4().hex[:8]
    payload: dict = {
        "customer": {
            "phone": _unique_phone(),
            "name": f"Nguyen Van {unique}",
            "email": f"customer-{unique}@example.com",
        },
        "shipping_address": "123 Nguyen Trai, District 1, HCMC",
        "note": "Please call before delivery",
        "items": [{"plant_id": str(plant.id), "quantity": 2}],
    }
    payload.update(overrides)
    return payload


async def _create_order(client: AsyncClient, plant: Plant, **overrides: object) -> dict:
    response = await client.post(ORDERS_PREFIX, json=_order_payload(plant, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def _stock(client: AsyncClient, plant: Plant) -> int:
    response = await client.get(f"{PLANTS_PREFIX}/{plant.id}")
    assert response.status_code == 200
    return int(response.json()["stock"])


async def _set_status(client: AsyncClient, order_id: str, status: str):
    return await client.patch(
        f"{ORDERS_PREFIX}/{order_id}/status",
        json={"status": status},
    )


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_orders_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(ORDERS_PREFIX)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_order_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(f"{ORDERS_PREFIX}/{uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_order_unauthenticated(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    response = await client.post(ORDERS_PREFIX, json=_order_payload(plant))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_order_status_unauthenticated(client: AsyncClient) -> None:
    response = await _set_status(client, str(uuid4()), "confirmed")
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_success(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    payload = _order_payload(plant)

    response = await client.post(ORDERS_PREFIX, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()

    assert ORDER_NUMBER_PATTERN.match(body["order_number"])
    assert body["status"] == "pending"
    assert body["shipping_address"] == payload["shipping_address"]
    assert body["note"] == payload["note"]
    assert body["customer"]["phone"] == payload["customer"]["phone"]
    assert body["customer"]["name"] == payload["customer"]["name"]
    assert body["customer"]["email"] == payload["customer"]["email"]
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["plant_id"] == str(plant.id)
    assert item["plant_name"] == plant.name
    assert item["quantity"] == 2
    assert item["unit_price"] == "300000.00"
    assert item["pot_size"] is None
    assert body["total_amount"] == "600000.00"
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_order_creates_new_customer(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    phone = _unique_phone()

    body = await _create_order(
        client,
        plant,
        customer={"phone": phone, "name": "Brand New", "email": "new@example.com"},
    )

    listed = await client.get(CUSTOMERS_PREFIX, params={"search": phone})
    items = listed.json()["items"]
    assert listed.json()["total"] == 1
    assert items[0]["id"] == body["customer"]["id"]
    assert items[0]["name"] == "Brand New"
    assert items[0]["email"] == "new@example.com"


@pytest.mark.asyncio
async def test_create_order_reuses_existing_customer(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """A known phone must never produce a second customer row."""
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    existing = await _seed_customer(test_db_session)

    first = await _create_order(
        client,
        plant,
        customer={"phone": existing.phone, "name": "Different Name"},
    )
    second = await _create_order(
        client,
        plant,
        customer={"phone": existing.phone, "name": "Another Name"},
    )

    assert first["customer"]["id"] == str(existing.id)
    assert second["customer"]["id"] == str(existing.id)

    listed = await client.get(CUSTOMERS_PREFIX, params={"search": existing.phone})
    assert listed.json()["total"] == 1
    # Stored customer data is preserved, not overwritten by the checkout form
    assert listed.json()["items"][0]["name"] == existing.name
    assert listed.json()["items"][0]["email"] == existing.email


@pytest.mark.asyncio
async def test_create_order_fills_missing_customer_email(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    existing = await _seed_customer(test_db_session, email=None)

    body = await _create_order(
        client,
        plant,
        customer={
            "phone": existing.phone,
            "name": existing.name,
            "email": "filled@example.com",
        },
    )
    assert body["customer"]["email"] == "filled@example.com"


@pytest.mark.asyncio
async def test_create_order_rejects_inactive_customer(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    customer = await _seed_customer(test_db_session, is_active=False)

    response = await client.post(
        ORDERS_PREFIX,
        json=_order_payload(
            plant,
            customer={"phone": customer.phone, "name": customer.name},
        ),
    )
    assert response.status_code == 400
    assert "inactive" in response.json()["detail"]
    assert await _stock(client, plant) == 20


@pytest.mark.asyncio
async def test_create_order_applies_pot_size_adjustment(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    await _seed_pot_size(test_db_session, plant)

    body = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 2, "pot_size": "Large"}],
    )

    item = body["items"][0]
    # 300000 plant price + 100000 pot size adjustment
    assert item["unit_price"] == "400000.00"
    assert item["pot_size"] == "Large"
    assert body["total_amount"] == "800000.00"


@pytest.mark.asyncio
async def test_create_order_pot_size_is_case_insensitive(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    await _seed_pot_size(test_db_session, plant)

    body = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": "large"}],
    )
    assert body["items"][0]["pot_size"] == "Large"
    assert body["items"][0]["unit_price"] == "400000.00"


@pytest.mark.asyncio
async def test_create_order_totals_multiple_items(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    first = await _seed_plant(test_db_session, test_category, price=Decimal("250000.00"))
    second = await _seed_plant(
        test_db_session,
        test_category,
        price=Decimal("125500.50"),
    )
    await _seed_pot_size(test_db_session, second, name="Medium")

    body = await _create_order(
        client,
        first,
        items=[
            {"plant_id": str(first.id), "quantity": 2},
            {"plant_id": str(second.id), "quantity": 3, "pot_size": "Medium"},
        ],
    )

    # 2 * 250000.00 + 3 * (125500.50 + 100000.00)
    assert body["total_amount"] == "1176501.50"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_create_order_ignores_client_supplied_money(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """The frontend must never be able to set prices or the total."""
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)

    payload = _order_payload(plant)
    payload["total_amount"] = "1.00"
    payload["status"] = "completed"
    payload["items"] = [
        {"plant_id": str(plant.id), "quantity": 2, "unit_price": "1.00"}
    ]

    response = await client.post(ORDERS_PREFIX, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["items"][0]["unit_price"] == "300000.00"
    assert body["total_amount"] == "600000.00"
    assert body["status"] == "pending"


@pytest.mark.asyncio
async def test_create_order_snapshots_plant_name_and_price(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """Renaming, repricing or retiring the plant must not rewrite history."""
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    order = await _create_order(client, plant)

    renamed = await client.patch(
        f"{PLANTS_PREFIX}/{plant.id}",
        json={"name": "Renamed Plant", "price": "999000.00"},
    )
    assert renamed.status_code == 200
    retired = await client.patch(
        f"{PLANTS_PREFIX}/{plant.id}/status",
        json={"is_active": False},
    )
    assert retired.status_code == 200

    detail = await client.get(f"{ORDERS_PREFIX}/{order['id']}")
    assert detail.status_code == 200
    item = detail.json()["items"][0]
    assert item["plant_name"] == plant.name
    assert item["unit_price"] == "300000.00"
    assert detail.json()["total_amount"] == "600000.00"


@pytest.mark.asyncio
async def test_create_order_deducts_stock(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=10)

    await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 3}],
    )
    assert await _stock(client, plant) == 7


@pytest.mark.asyncio
async def test_create_order_insufficient_stock(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=1)
    phone = _unique_phone()

    response = await client.post(
        ORDERS_PREFIX,
        json=_order_payload(
            plant,
            customer={"phone": phone, "name": "Too Greedy"},
            items=[{"plant_id": str(plant.id), "quantity": 5}],
        ),
    )
    assert response.status_code == 400
    assert "stock" in response.json()["detail"].lower()

    # Neither the order, the customer nor the stock may have changed
    assert await _stock(client, plant) == 1
    orders = await client.get(ORDERS_PREFIX, params={"search": phone})
    assert orders.json()["total"] == 0
    customers = await client.get(CUSTOMERS_PREFIX, params={"search": phone})
    assert customers.json()["total"] == 0


@pytest.mark.asyncio
async def test_create_order_sums_quantity_per_plant_for_stock(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """Repeated lines for one plant cannot slip past the stock check."""
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=4)
    await _seed_pot_size(test_db_session, plant)

    response = await client.post(
        ORDERS_PREFIX,
        json=_order_payload(
            plant,
            items=[
                {"plant_id": str(plant.id), "quantity": 3},
                {"plant_id": str(plant.id), "quantity": 3, "pot_size": "Large"},
            ],
        ),
    )
    assert response.status_code == 400
    assert await _stock(client, plant) == 4


@pytest.mark.asyncio
async def test_create_order_unknown_plant(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)

    response = await client.post(
        ORDERS_PREFIX,
        json=_order_payload(
            plant,
            items=[{"plant_id": str(uuid4()), "quantity": 1}],
        ),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Plant not found"


@pytest.mark.asyncio
async def test_create_order_inactive_plant(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, is_active=False)

    response = await client.post(ORDERS_PREFIX, json=_order_payload(plant))
    assert response.status_code == 400
    assert "not available" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_order_unknown_pot_size(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    await _seed_pot_size(test_db_session, plant)

    response = await client.post(
        ORDERS_PREFIX,
        json=_order_payload(
            plant,
            items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": "Gigantic"}],
        ),
    )
    assert response.status_code == 400
    assert "Gigantic" in response.json()["detail"]
    assert await _stock(client, plant) == 20


@pytest.mark.asyncio
async def test_create_order_inactive_pot_size(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    await _seed_pot_size(test_db_session, plant, is_active=False)

    response = await client.post(
        ORDERS_PREFIX,
        json=_order_payload(
            plant,
            items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": "Large"}],
        ),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"items": []},
        {"shipping_address": "   "},
        {"customer": {"phone": "", "name": "No Phone"}},
        {"customer": {"phone": "0901234567"}},
    ],
)
async def test_create_order_invalid_payload(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
    overrides: dict,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)

    response = await client.post(ORDERS_PREFIX, json=_order_payload(plant, **overrides))
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [0, -1])
async def test_create_order_invalid_quantity(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
    quantity: int,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)

    response = await client.post(
        ORDERS_PREFIX,
        json=_order_payload(
            plant,
            items=[{"plant_id": str(plant.id), "quantity": quantity}],
        ),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_order_numbers_are_unique_and_sequential(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)

    numbers = [(await _create_order(client, plant))["order_number"] for _ in range(3)]
    assert len(set(numbers)) == 3
    for number in numbers:
        assert ORDER_NUMBER_PATTERN.match(number)
    today = datetime.now(UTC).strftime("%Y%m%d")
    assert all(number.startswith(f"GG-{today}-") for number in numbers)


# --------------------------------------------------------------------------
# Detail
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_detail(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    await _seed_pot_size(test_db_session, plant)
    created = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 2, "pot_size": "Large"}],
    )

    response = await client.get(f"{ORDERS_PREFIX}/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["order_number"] == created["order_number"]
    assert body["total_amount"] == "800000.00"
    assert body["shipping_address"] == created["shipping_address"]
    assert body["note"] == created["note"]
    assert set(body["customer"]) == {"id", "name", "phone", "email"}
    assert set(body["items"][0]) == {
        "id",
        "plant_id",
        "plant_name",
        "quantity",
        "unit_price",
        "pot_size",
    }


@pytest.mark.asyncio
async def test_get_order_not_found(client: AsyncClient, active_admin: Admin) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{ORDERS_PREFIX}/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


@pytest.mark.asyncio
async def test_get_order_invalid_uuid(client: AsyncClient, active_admin: Admin) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{ORDERS_PREFIX}/not-a-uuid")
    assert response.status_code == 422


# --------------------------------------------------------------------------
# List
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_orders_includes_customer_and_items(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    created = await _create_order(client, plant)

    response = await client.get(
        ORDERS_PREFIX,
        params={"search": created["order_number"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["customer"]["phone"] == created["customer"]["phone"]
    assert row["items"][0]["plant_name"] == plant.name


@pytest.mark.asyncio
async def test_list_orders_pagination(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    customer = await _seed_customer(test_db_session)
    for _ in range(3):
        await _create_order(
            client,
            plant,
            customer={"phone": customer.phone, "name": customer.name},
            items=[{"plant_id": str(plant.id), "quantity": 1}],
        )

    first = await client.get(
        ORDERS_PREFIX,
        params={"customer_id": str(customer.id), "page": 1, "page_size": 2},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2

    second = await client.get(
        ORDERS_PREFIX,
        params={"customer_id": str(customer.id), "page": 2, "page_size": 2},
    )
    assert len(second.json()["items"]) == 1


@pytest.mark.asyncio
async def test_list_orders_invalid_page_size(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(ORDERS_PREFIX, params={"page_size": 500})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_orders_by_number_phone_and_name(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    marker = uuid4().hex[:8]
    phone = _unique_phone()
    created = await _create_order(
        client,
        plant,
        customer={"phone": phone, "name": f"Findable {marker}"},
    )
    await _create_order(client, plant)

    by_number = await client.get(
        ORDERS_PREFIX,
        params={"search": created["order_number"]},
    )
    assert [row["id"] for row in by_number.json()["items"]] == [created["id"]]

    by_phone = await client.get(ORDERS_PREFIX, params={"search": phone})
    assert [row["id"] for row in by_phone.json()["items"]] == [created["id"]]

    by_name = await client.get(ORDERS_PREFIX, params={"search": f"Findable {marker}"})
    assert [row["id"] for row in by_name.json()["items"]] == [created["id"]]


@pytest.mark.asyncio
async def test_filter_orders_by_status_and_customer(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    customer = await _seed_customer(test_db_session)
    confirmed = await _create_order(
        client,
        plant,
        customer={"phone": customer.phone, "name": customer.name},
        items=[{"plant_id": str(plant.id), "quantity": 1}],
    )
    pending = await _create_order(
        client,
        plant,
        customer={"phone": customer.phone, "name": customer.name},
        items=[{"plant_id": str(plant.id), "quantity": 1}],
    )
    assert (await _set_status(client, confirmed["id"], "confirmed")).status_code == 200

    by_status = await client.get(
        ORDERS_PREFIX,
        params={"customer_id": str(customer.id), "status": "confirmed"},
    )
    assert [row["id"] for row in by_status.json()["items"]] == [confirmed["id"]]

    by_customer = await client.get(
        ORDERS_PREFIX,
        params={"customer_id": str(customer.id)},
    )
    assert {row["id"] for row in by_customer.json()["items"]} == {
        confirmed["id"],
        pending["id"],
    }

    other_customer = await client.get(
        ORDERS_PREFIX,
        params={"customer_id": str(uuid4())},
    )
    assert other_customer.json()["total"] == 0


@pytest.mark.asyncio
async def test_filter_orders_by_invalid_status(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(ORDERS_PREFIX, params={"status": "paid"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_filter_orders_by_date_range(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    created = await _create_order(client, plant)
    number = created["order_number"]

    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()

    inside = await client.get(
        ORDERS_PREFIX,
        params={"search": number, "date_from": today.isoformat(), "date_to": tomorrow},
    )
    assert [row["id"] for row in inside.json()["items"]] == [created["id"]]

    before = await client.get(
        ORDERS_PREFIX,
        params={"search": number, "date_to": yesterday},
    )
    assert before.json()["total"] == 0

    after = await client.get(
        ORDERS_PREFIX,
        params={"search": number, "date_from": tomorrow},
    )
    assert after.json()["total"] == 0


@pytest.mark.asyncio
async def test_filter_orders_by_invalid_date(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(ORDERS_PREFIX, params={"date_from": "16-09-2026"})
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_order_status_through_the_pipeline(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    created = await _create_order(client, plant)

    for status_value in ("confirmed", "processing", "shipping", "completed"):
        response = await _set_status(client, created["id"], status_value)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == status_value
        # Nothing but the status may change
        assert body["total_amount"] == created["total_amount"]
        assert body["order_number"] == created["order_number"]
        assert body["shipping_address"] == created["shipping_address"]
        assert body["note"] == created["note"]
        assert body["items"] == created["items"]
        assert body["customer"] == created["customer"]

    # Stock stays deducted for a completed order
    assert await _stock(client, plant) == 18


@pytest.mark.asyncio
async def test_update_order_status_rejects_unknown_value(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    created = await _create_order(client, plant)

    for value in ("paid", "PENDING", "", "refunded"):
        response = await _set_status(client, created["id"], value)
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_order_status_rejects_backwards_transition(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    created = await _create_order(client, plant)
    assert (await _set_status(client, created["id"], "shipping")).status_code == 200

    response = await _set_status(client, created["id"], "confirmed")
    assert response.status_code == 400
    assert "shipping" in response.json()["detail"]


@pytest.mark.asyncio
async def test_completed_order_status_is_final(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    created = await _create_order(client, plant)
    assert (await _set_status(client, created["id"], "completed")).status_code == 200

    response = await _set_status(client, created["id"], "cancelled")
    assert response.status_code == 400
    assert await _stock(client, plant) == 18


@pytest.mark.asyncio
async def test_order_status_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await _set_status(client, str(uuid4()), "confirmed")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Cancellation and stock restoration
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_order_restores_stock(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=10)
    created = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 4}],
    )
    assert await _stock(client, plant) == 6

    response = await _set_status(client, created["id"], "cancelled")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert await _stock(client, plant) == 10
    # The order and its snapshots are kept as a historical record
    assert response.json()["items"] == created["items"]


@pytest.mark.asyncio
async def test_cancel_order_twice_does_not_restore_stock_twice(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=10)
    created = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 4}],
    )
    assert (await _set_status(client, created["id"], "cancelled")).status_code == 200
    assert await _stock(client, plant) == 10

    repeated = await _set_status(client, created["id"], "cancelled")
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "cancelled"
    assert await _stock(client, plant) == 10

    third = await _set_status(client, created["id"], "cancelled")
    assert third.status_code == 200
    assert await _stock(client, plant) == 10


@pytest.mark.asyncio
async def test_cancelled_order_cannot_be_reopened(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=10)
    created = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 4}],
    )
    assert (await _set_status(client, created["id"], "cancelled")).status_code == 200

    response = await _set_status(client, created["id"], "confirmed")
    assert response.status_code == 400
    assert await _stock(client, plant) == 10


@pytest.mark.asyncio
async def test_cancel_order_restores_stock_for_every_line(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    first = await _seed_plant(test_db_session, test_category, stock=10)
    second = await _seed_plant(test_db_session, test_category, stock=8)
    created = await _create_order(
        client,
        first,
        items=[
            {"plant_id": str(first.id), "quantity": 2},
            {"plant_id": str(second.id), "quantity": 3},
        ],
    )
    assert await _stock(client, first) == 8
    assert await _stock(client, second) == 5

    assert (await _set_status(client, created["id"], "cancelled")).status_code == 200
    assert await _stock(client, first) == 10
    assert await _stock(client, second) == 8


@pytest.mark.asyncio
async def test_cancel_after_shipping_restores_stock_once(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=10)
    created = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 2}],
    )
    for status_value in ("confirmed", "processing", "shipping"):
        assert (await _set_status(client, created["id"], status_value)).status_code == 200
    assert await _stock(client, plant) == 8

    assert (await _set_status(client, created["id"], "cancelled")).status_code == 200
    assert await _stock(client, plant) == 10


@pytest.mark.asyncio
async def test_repeating_current_status_changes_nothing(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=10)
    created = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 2}],
    )

    response = await _set_status(client, created["id"], "pending")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["updated_at"] == created["updated_at"]
    assert await _stock(client, plant) == 8


# --------------------------------------------------------------------------
# No hard delete
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_delete_endpoint_for_orders(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category)
    created = await _create_order(client, plant)

    response = await client.delete(f"{ORDERS_PREFIX}/{created['id']}")
    assert response.status_code == 405


# --------------------------------------------------------------------------
# Query efficiency
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_reads_avoid_n_plus_one(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """Listing and detail must eager-load customers and items."""
    await _login(client, active_admin)
    plant = await _seed_plant(test_db_session, test_category, stock=50)
    customer = await _seed_customer(test_db_session)
    for _ in range(5):
        await _create_order(
            client,
            plant,
            customer={"phone": customer.phone, "name": customer.name},
            items=[{"plant_id": str(plant.id), "quantity": 1}],
        )

    # Start from a clean identity map so the reads behave like fresh requests.
    test_db_session.expunge_all()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        statements.clear()
        orders, total = await list_orders(
            test_db_session,
            page=1,
            page_size=5,
            customer_id=customer.id,
        )
        list_queries = len(statements)

        test_db_session.expunge_all()

        statements.clear()
        detail = await get_order(test_db_session, orders[0].id)
        detail_queries = len(statements)
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

    assert total == 5
    assert len(orders) == 5
    # count + rows + customers + items
    assert list_queries <= 4
    # order + customer + items
    assert detail_queries <= 3
    assert detail.customer.id == customer.id
    assert len(detail.items) == 1
