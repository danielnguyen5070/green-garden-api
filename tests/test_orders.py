"""Orders API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_vn_phone
from app.models.admin import Admin
from app.models.category import Category
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.plant import Plant
from app.models.plant_pot_size import PlantPotSize
from app.services.order_service import get_order, list_orders


AUTH_PREFIX = "/api/v1/auth"
CUSTOMERS_PREFIX = "/api/v1/customers"
ORDERS_PREFIX = "/api/v1/orders"
PLANTS_PREFIX = "/api/v1/plants"
CHECKOUT_PATH = "/api/v1/storefront/orders"

ORDER_NUMBER_PATTERN = re.compile(r"^GG-\d{8}-\d{4}$")

# Storefront shipping: flat fee at or below the threshold, free above it.
SHIPPING_FEE = Decimal("50000.00")
FREE_SHIPPING_ABOVE = Decimal("500000.00")


def _expected_total(subtotal: Decimal) -> str:
    shipping = Decimal("0.00") if subtotal > FREE_SHIPPING_ABOVE else SHIPPING_FEE
    return str((subtotal + shipping).quantize(Decimal("0.01")))


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


async def _seed_vi_plant(
    session: AsyncSession,
    category: Category,
    *,
    price_vi: Decimal = Decimal("300000.00"),
    **overrides: object,
) -> Plant:
    """
    A storefront catalogue row.

    The default-locale columns hold decoy values the checkout must never use:
    if an assertion below ever matches `price`, the storefront priced the order
    in the wrong currency.
    """
    unique = uuid4().hex[:8]
    values: dict = {
        "name_vi": f"Cây Trầu Bà {unique}",
        "price": price_vi + Decimal("111111.11"),
        "price_vi": price_vi,
        "stock": 20,
    }
    values.update(overrides)
    return await _seed_plant(session, category, **values)


async def _seed_vi_pot_size(
    session: AsyncSession,
    plant: Plant,
    *,
    price_adjustment_vi: Decimal | None = Decimal("60000.00"),
    **overrides: object,
) -> PlantPotSize:
    """A pot size whose Vietnamese adjustment differs from the English one."""
    values: dict = {
        "name": "Chậu 20cm",
        "price_adjustment": Decimal("7777.77"),
        "price_adjustment_vi": price_adjustment_vi,
    }
    values.update(overrides)
    return await _seed_pot_size(session, plant, **values)


def _checkout_payload(plant: Plant, **overrides: object) -> dict:
    """Exactly what the public checkout form collects — no email, no prices."""
    payload: dict = {
        "customer": {"phone": _unique_phone(), "name": "Nguyễn Văn A"},
        "shipping_address": "123 Nguyễn Huệ, Quận 1, TP.HCM",
        "note": "Giao giờ hành chính",
        "items": [{"plant_id": str(plant.id), "quantity": 1}],
    }
    payload.update(overrides)
    return payload


async def _checkout(client: AsyncClient, plant: Plant, **overrides: object):
    return await client.post(CHECKOUT_PATH, json=_checkout_payload(plant, **overrides))


async def _db_stock(session: AsyncSession, plant: Plant) -> int:
    """Read stock straight from the database, without admin authentication."""
    result = await session.execute(select(Plant.stock).where(Plant.id == plant.id))
    return int(result.scalar_one())


async def _orders_for_phone(session: AsyncSession, phone: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Order)
        .join(Customer, Order.customer_id == Customer.id)
        .where(Customer.phone == phone)
    )
    return int(result.scalar_one())


async def _checkout_items(session: AsyncSession, order_id: str) -> list[OrderItem]:
    """Item snapshots straight from the database, without admin authentication."""
    result = await session.execute(
        select(OrderItem).where(OrderItem.order_id == UUID(order_id))
    )
    return list(result.scalars().all())


async def _customer_by_phone(session: AsyncSession, phone: str) -> Customer | None:
    result = await session.execute(select(Customer).where(Customer.phone == phone))
    return result.scalar_one_or_none()


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
async def test_create_order_prices_from_the_default_locale_columns(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """The admin panel keeps selling at `price`, with no shipping fee added."""
    await _login(client, active_admin)
    plant = await _seed_plant(
        test_db_session,
        test_category,
        price=Decimal("300000.00"),
        name_vi="Cây Trầu Bà",
        price_vi=Decimal("111000.00"),
    )
    await _seed_pot_size(
        test_db_session,
        plant,
        price_adjustment=Decimal("100000.00"),
        price_adjustment_vi=Decimal("1.00"),
    )

    body = await _create_order(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": "Large"}],
    )

    item = body["items"][0]
    assert item["plant_name"] == plant.name
    assert item["unit_price"] == "400000.00"
    # The total is exactly the subtotal: admin orders carry no shipping fee
    assert body["total_amount"] == "400000.00"


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
# Public storefront checkout (cash on delivery, no authentication)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_requires_no_authentication(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)

    response = await _checkout(client, plant)

    assert not client.cookies
    assert response.status_code == 201, response.text
    # The checkout never hands out a session of any kind.
    assert not response.cookies


@pytest.mark.asyncio
async def test_checkout_returns_the_confirmation_fields_only(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("240000.00"),
    )

    response = await _checkout(client, plant)
    assert response.status_code == 201, response.text
    body = response.json()

    assert set(body) == {"id", "order_number", "status", "total_amount", "created_at"}
    assert ORDER_NUMBER_PATTERN.match(body["order_number"])
    assert body["status"] == "pending"
    # 240000.00 subtotal + 50000.00 shipping
    assert body["total_amount"] == "290000.00"


@pytest.mark.asyncio
async def test_checkout_creates_a_new_customer(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    phone = _unique_phone()

    response = await _checkout(
        client,
        plant,
        customer={"phone": phone, "name": "  Nguyễn Văn B  "},
    )
    assert response.status_code == 201, response.text

    customer = await _customer_by_phone(test_db_session, phone)
    assert customer is not None
    assert customer.name == "Nguyễn Văn B"
    assert customer.email is None
    assert customer.is_active is True


@pytest.mark.asyncio
async def test_checkout_reuses_an_existing_customer_by_phone(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    existing = await _seed_customer(test_db_session, name="Original Name")

    response = await _checkout(
        client,
        plant,
        customer={"phone": existing.phone, "name": "Typed A Different Name"},
    )
    assert response.status_code == 201, response.text

    # One customer row, and the stored name wins — the existing convention.
    result = await test_db_session.execute(
        select(Customer).where(Customer.phone == existing.phone)
    )
    customers = result.scalars().all()
    assert len(customers) == 1
    assert customers[0].id == existing.id
    assert customers[0].name == "Original Name"


@pytest.mark.asyncio
async def test_checkout_prices_multiple_items_and_quantities(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    first = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("150000.00"),
    )
    second = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("90000.50"),
    )
    phone = _unique_phone()

    response = await _checkout(
        client,
        first,
        customer={"phone": phone, "name": "Nguyễn Văn A"},
        items=[
            {"plant_id": str(first.id), "quantity": 3},
            {"plant_id": str(second.id), "quantity": 2},
        ],
    )
    assert response.status_code == 201, response.text
    # 3 × 150000.00 + 2 × 90000.50 = 630001.00, above the free shipping threshold
    assert response.json()["total_amount"] == "630001.00"

    await _login(client, active_admin)
    detail = await client.get(f"{ORDERS_PREFIX}/{response.json()['id']}")
    items = {item["plant_id"]: item for item in detail.json()["items"]}
    assert items[str(first.id)]["quantity"] == 3
    assert items[str(first.id)]["unit_price"] == "150000.00"
    assert items[str(first.id)]["plant_name"] == first.name_vi
    assert items[str(second.id)]["unit_price"] == "90000.50"


@pytest.mark.asyncio
async def test_checkout_adds_the_pot_size_price_adjustment(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("300000.00"),
    )
    await _seed_vi_pot_size(
        test_db_session,
        plant,
        price_adjustment_vi=Decimal("60000.00"),
    )

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 2, "pot_size": "Chậu 20cm"}],
    )
    assert response.status_code == 201, response.text
    # 2 × (300000.00 price_vi + 60000.00 price_adjustment_vi), free shipping
    assert response.json()["total_amount"] == "720000.00"

    await _login(client, active_admin)
    detail = await client.get(f"{ORDERS_PREFIX}/{response.json()['id']}")
    item = detail.json()["items"][0]
    assert item["unit_price"] == "360000.00"
    assert item["pot_size"] == "Chậu 20cm"


@pytest.mark.asyncio
async def test_checkout_ignores_prices_sent_by_the_frontend(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("500000.00"),
    )

    response = await client.post(
        CHECKOUT_PATH,
        json={
            "customer": {"phone": _unique_phone(), "name": "Nguyễn Văn A"},
            "shipping_address": "123 Nguyễn Huệ, Quận 1, TP.HCM",
            "total_amount": "1.00",
            "subtotal": "1.00",
            "shipping_fee": "0.00",
            "items": [
                {
                    "plant_id": str(plant.id),
                    "quantity": 2,
                    "unit_price": "1.00",
                    "price": "1.00",
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["total_amount"] == "1000000.00"


@pytest.mark.asyncio
async def test_checkout_decreases_stock(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 4}],
    )

    assert response.status_code == 201, response.text
    assert await _db_stock(test_db_session, plant) == 6


@pytest.mark.asyncio
async def test_checkout_with_insufficient_stock_returns_409(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=2)
    phone = _unique_phone()

    response = await _checkout(
        client,
        plant,
        customer={"phone": phone, "name": "Nguyễn Văn A"},
        items=[{"plant_id": str(plant.id), "quantity": 5}],
    )

    assert response.status_code == 409
    assert "stock" in response.json()["detail"].lower()
    assert await _db_stock(test_db_session, plant) == 2
    assert await _orders_for_phone(test_db_session, phone) == 0


@pytest.mark.asyncio
async def test_checkout_does_not_partially_deduct_stock(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """A rejected line rolls the whole checkout back, including the good line."""
    available = await _seed_vi_plant(test_db_session, test_category, stock=10)
    scarce = await _seed_vi_plant(test_db_session, test_category, stock=1)
    phone = _unique_phone()

    response = await _checkout(
        client,
        available,
        customer={"phone": phone, "name": "Nguyễn Văn A"},
        items=[
            {"plant_id": str(available.id), "quantity": 2},
            {"plant_id": str(scarce.id), "quantity": 5},
        ],
    )

    assert response.status_code == 409
    assert await _db_stock(test_db_session, available) == 10
    assert await _db_stock(test_db_session, scarce) == 1
    assert await _orders_for_phone(test_db_session, phone) == 0


@pytest.mark.asyncio
async def test_checkout_rejects_inactive_plant_with_409(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        is_active=False,
    )

    response = await _checkout(client, plant)

    assert response.status_code == 409
    assert "not available" in response.json()["detail"]
    assert await _db_stock(test_db_session, plant) == 10


@pytest.mark.asyncio
async def test_checkout_unknown_plant_returns_404(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(uuid4()), "quantity": 1}],
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Plant not found"


@pytest.mark.asyncio
async def test_checkout_unknown_pot_size_returns_404(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    await _seed_vi_pot_size(test_db_session, plant)

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": "Chậu 90cm"}],
    )

    assert response.status_code == 404
    assert "Chậu 90cm" in response.json()["detail"]
    assert await _db_stock(test_db_session, plant) == 10


@pytest.mark.asyncio
async def test_checkout_inactive_pot_size_returns_404(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    await _seed_vi_pot_size(
        test_db_session,
        plant,
        name="Retired",
        is_active=False,
    )

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": "Retired"}],
    )

    assert response.status_code == 404
    assert await _db_stock(test_db_session, plant) == 10


@pytest.mark.asyncio
async def test_checkout_rejects_deactivated_customer_with_400(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    retired = await _seed_customer(test_db_session, is_active=False)

    response = await _checkout(
        client,
        plant,
        customer={"phone": retired.phone, "name": "Nguyễn Văn A"},
    )

    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()
    assert await _db_stock(test_db_session, plant) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_override",
    [
        pytest.param({"items": []}, id="no-items"),
        pytest.param({"customer": {"phone": "0901234567"}}, id="missing-name"),
        pytest.param({"customer": {"name": "Nguyễn Văn A"}}, id="missing-phone"),
        pytest.param({"customer": {"phone": "abc", "name": "A"}}, id="bad-phone"),
        pytest.param({"shipping_address": "   "}, id="blank-address"),
    ],
)
async def test_checkout_invalid_body_returns_422(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    payload_override: dict,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)

    response = await _checkout(client, plant, **payload_override)

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [0, -1, "two", 1.5])
async def test_checkout_invalid_quantity_returns_422(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    quantity: object,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": quantity}],
    )

    assert response.status_code == 422
    assert await _db_stock(test_db_session, plant) == 10


@pytest.mark.asyncio
async def test_checkout_invalid_plant_id_returns_422(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": "not-a-uuid", "quantity": 1}],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_checkout_order_is_visible_to_the_admin_panel(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """Cart → checkout → customer, order, items and stock, then admin sees it."""
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("120000.00"),
    )
    phone = _unique_phone()

    checkout = await _checkout(
        client,
        plant,
        customer={"phone": phone, "name": "Nguyễn Văn A"},
        items=[{"plant_id": str(plant.id), "quantity": 2}],
    )
    assert checkout.status_code == 201, checkout.text

    await _login(client, active_admin)
    listed = await client.get(ORDERS_PREFIX, params={"search": phone})
    assert listed.status_code == 200
    body = listed.json()

    assert body["total"] == 1
    order = body["items"][0]
    assert order["id"] == checkout.json()["id"]
    assert order["order_number"] == checkout.json()["order_number"]
    assert order["status"] == "pending"
    # 2 × 120000.00 subtotal + 50000.00 shipping
    assert order["total_amount"] == "290000.00"
    assert order["shipping_address"] == "123 Nguyễn Huệ, Quận 1, TP.HCM"
    assert order["note"] == "Giao giờ hành chính"
    assert order["customer"]["phone"] == phone
    assert order["customer"]["email"] is None
    assert len(order["items"]) == 1
    assert order["items"][0]["plant_name"] == plant.name_vi
    assert order["items"][0]["unit_price"] == "120000.00"
    assert await _db_stock(test_db_session, plant) == 8


# --------------------------------------------------------------------------
# Storefront pricing: Vietnamese product data only
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_snapshots_the_vietnamese_name_and_price(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """`name_vi` and `price_vi` are the only product columns the shop may use."""
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("250000.00"),
    )

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 2}],
    )
    assert response.status_code == 201, response.text

    items = await _checkout_items(test_db_session, response.json()["id"])
    assert len(items) == 1
    assert items[0].plant_name == plant.name_vi
    assert items[0].plant_name != plant.name
    assert items[0].quantity == 2
    assert items[0].unit_price == Decimal("250000.00")
    assert items[0].unit_price != plant.price
    # 2 × 250000.00 = 500000.00, exactly on the threshold, so shipping is charged
    assert response.json()["total_amount"] == "550000.00"


@pytest.mark.asyncio
@pytest.mark.parametrize("name_vi", [None, "   "], ids=["null", "blank"])
async def test_checkout_falls_back_to_the_default_name_without_name_vi(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    name_vi: str | None,
) -> None:
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        name_vi=name_vi,
    )

    response = await _checkout(client, plant)
    assert response.status_code == 201, response.text

    items = await _checkout_items(test_db_session, response.json()["id"])
    assert items[0].plant_name == plant.name


@pytest.mark.asyncio
async def test_checkout_adds_only_the_vietnamese_pot_size_adjustment(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("200000.00"),
    )
    pot_size = await _seed_vi_pot_size(
        test_db_session,
        plant,
        price_adjustment=Decimal("15.00"),
        price_adjustment_vi=Decimal("45000.00"),
    )

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": pot_size.name}],
    )
    assert response.status_code == 201, response.text

    items = await _checkout_items(test_db_session, response.json()["id"])
    # 200000.00 + 45000.00, never 200000.00 + 15.00
    assert items[0].unit_price == Decimal("245000.00")
    assert items[0].pot_size == pot_size.name
    assert response.json()["total_amount"] == "295000.00"


@pytest.mark.asyncio
async def test_checkout_treats_a_missing_vietnamese_adjustment_as_zero(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """A pot size without `price_adjustment_vi` costs nothing extra."""
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("200000.00"),
    )
    pot_size = await _seed_vi_pot_size(
        test_db_session,
        plant,
        price_adjustment=Decimal("99000.00"),
        price_adjustment_vi=None,
    )

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": 1, "pot_size": pot_size.name}],
    )
    assert response.status_code == 201, response.text

    items = await _checkout_items(test_db_session, response.json()["id"])
    assert items[0].unit_price == Decimal("200000.00")
    assert response.json()["total_amount"] == "250000.00"


@pytest.mark.asyncio
async def test_checkout_rejects_a_plant_without_a_vietnamese_price(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """Rather than fall back to `price`, the shop refuses to sell the plant."""
    plant = await _seed_plant(test_db_session, test_category, stock=10, price_vi=None)

    response = await _checkout(client, plant)

    assert response.status_code == 409
    assert "not available" in response.json()["detail"]
    assert await _db_stock(test_db_session, plant) == 10


# --------------------------------------------------------------------------
# Storefront shipping fee
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("price_vi", "quantity", "expected_total"),
    [
        pytest.param(Decimal("225000.00"), 2, "500000.00", id="450000-pays-50000"),
        pytest.param(Decimal("500000.00"), 1, "550000.00", id="500000-pays-50000"),
        pytest.param(Decimal("500001.00"), 1, "500001.00", id="500001-ships-free"),
        pytest.param(Decimal("400000.00"), 2, "800000.00", id="800000-ships-free"),
    ],
)
async def test_checkout_charges_shipping_up_to_the_threshold(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    price_vi: Decimal,
    quantity: int,
    expected_total: str,
) -> None:
    """Free shipping starts above 500,000 VND — exactly 500,000 still pays."""
    plant = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=price_vi,
    )

    response = await _checkout(
        client,
        plant,
        items=[{"plant_id": str(plant.id), "quantity": quantity}],
    )

    assert response.status_code == 201, response.text
    assert response.json()["total_amount"] == expected_total


@pytest.mark.asyncio
async def test_checkout_total_is_the_item_subtotal_plus_shipping(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    first = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("100000.00"),
    )
    second = await _seed_vi_plant(
        test_db_session,
        test_category,
        stock=10,
        price_vi=Decimal("60000.50"),
    )

    response = await _checkout(
        client,
        first,
        items=[
            {"plant_id": str(first.id), "quantity": 2},
            {"plant_id": str(second.id), "quantity": 3},
        ],
    )
    assert response.status_code == 201, response.text

    items = await _checkout_items(test_db_session, response.json()["id"])
    subtotal = sum(
        (item.unit_price * item.quantity for item in items),
        start=Decimal("0.00"),
    )
    # 2 × 100000.00 + 3 × 60000.50 = 380001.50, so 50000.00 shipping applies
    assert subtotal == Decimal("380001.50")
    assert response.json()["total_amount"] == _expected_total(subtotal)
    assert response.json()["total_amount"] == "430001.50"


# --------------------------------------------------------------------------
# Storefront phone normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("+84901234567", "0901234567"),
        ("84901234567", "0901234567"),
        ("0901234567", "0901234567"),
        ("+84 90 123 4567", "0901234567"),
        ("090-123-4567", "0901234567"),
        # Written by hand often enough to be worth handling
        ("+840901234567", "0901234567"),
        # Not a Vietnamese number: separators go, the number stays
        ("+61412345678", "+61412345678"),
        ("8412345", "8412345"),
    ],
)
def test_normalize_vn_phone(typed: str, expected: str) -> None:
    assert normalize_vn_phone(typed) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prefix",
    ["+84", "84", "0"],
    ids=["international", "country-code", "local"],
)
async def test_checkout_stores_the_canonical_phone(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    prefix: str,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    canonical = _unique_phone()
    typed = f"{prefix}{canonical[1:]}"

    response = await _checkout(
        client,
        plant,
        customer={"phone": typed, "name": "Nguyễn Văn A"},
    )
    assert response.status_code == 201, response.text

    stored = await _customer_by_phone(test_db_session, canonical)
    assert stored is not None
    assert stored.phone == canonical
    if typed != canonical:
        assert await _customer_by_phone(test_db_session, typed) is None


@pytest.mark.asyncio
async def test_checkout_reuses_one_customer_across_phone_formats(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """`+84…`, `84…` and `0…` are the same shopper, not three customers."""
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    canonical = _unique_phone()
    formats = [f"+84{canonical[1:]}", f"84{canonical[1:]}", canonical]

    for phone in formats:
        response = await _checkout(
            client,
            plant,
            customer={"phone": phone, "name": "Nguyễn Văn A"},
        )
        assert response.status_code == 201, response.text

    result = await test_db_session.execute(
        select(Customer).where(Customer.phone.in_(formats))
    )
    customers = result.scalars().all()
    assert len(customers) == 1
    assert customers[0].phone == canonical
    assert await _orders_for_phone(test_db_session, canonical) == 3


@pytest.mark.asyncio
async def test_checkout_finds_an_existing_customer_typed_internationally(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_vi_plant(test_db_session, test_category, stock=10)
    existing = await _seed_customer(test_db_session, name="Original Name")

    response = await _checkout(
        client,
        plant,
        customer={"phone": f"+84{existing.phone[1:]}", "name": "Nguyễn Văn A"},
    )
    assert response.status_code == 201, response.text

    stored = await _customer_by_phone(test_db_session, existing.phone)
    assert stored is not None
    assert stored.id == existing.id
    assert await _orders_for_phone(test_db_session, existing.phone) == 1


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
