"""Dashboard overview API tests (run against TEST_DATABASE_URL).

The overview counts every row in the database, so each test starts from an
empty shop: the business tables are truncated first. `admins` is left alone —
the login fixtures own it, and the overview never counts admins.

Timestamps are always built from `datetime.now(UTC)` so the assertions hold on
any day of any month, including the 1st.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import NamedTuple
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.category import Category
from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.plant import Plant
from app.services.overview_service import build_overview

AUTH_PREFIX = "/api/v1/auth"
OVERVIEW_PATH = "/api/v1/overview"

MONEY_PATTERN = re.compile(r"^-?\d+\.\d{2}$")

_ORDER_SEQUENCE = count(1)

# Tables the overview reads; admins stay in place for the auth fixtures.
_SHOP_TABLES = (
    "order_items",
    "orders",
    "plant_pot_sizes",
    "plant_images",
    "plants",
    "customers",
    "categories",
)


@pytest_asyncio.fixture(autouse=True)
async def empty_shop(test_db_session: AsyncSession) -> None:
    await test_db_session.execute(
        text(f"TRUNCATE {', '.join(_SHOP_TABLES)} CASCADE")
    )
    await test_db_session.commit()


class _Item(NamedTuple):
    """One line to seed on an order, with an optional snapshot name override."""

    plant: Plant
    quantity: int
    unit_price: Decimal
    plant_name: str | None = None


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


async def _overview(client: AsyncClient) -> dict:
    response = await client.get(OVERVIEW_PATH)
    assert response.status_code == 200, response.text
    return response.json()


async def _seed_category(session: AsyncSession, **overrides: object) -> Category:
    unique = uuid4().hex[:8]
    values: dict = {
        "name": f"Indoor Plants {unique}",
        "slug": f"indoor-plants-{unique}",
        "is_active": True,
    }
    values.update(overrides)
    category = Category(**values)
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


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


async def _seed_customer(session: AsyncSession, **overrides: object) -> Customer:
    unique = uuid4().hex[:8]
    values: dict = {
        "phone": f"09{uuid4().int % 100_000_000:08d}",
        "name": f"Nguyen Van {unique}",
        "email": f"customer-{unique}@example.com",
        "is_active": True,
    }
    values.update(overrides)
    customer = Customer(**values)
    session.add(customer)
    await session.commit()
    await session.refresh(customer)
    return customer


async def _seed_order(
    session: AsyncSession,
    customer: Customer,
    *,
    status: OrderStatus = OrderStatus.PENDING,
    total_amount: Decimal = Decimal("100000.00"),
    created_at: datetime | None = None,
    items: tuple[_Item, ...] = (),
) -> Order:
    """Insert an order directly so status and `created_at` can be chosen."""
    created = created_at or datetime.now(UTC)
    order = Order(
        customer_id=customer.id,
        order_number=(
            f"GG-{created.strftime('%Y%m%d')}-{next(_ORDER_SEQUENCE):04d}"
        ),
        status=status,
        total_amount=total_amount,
        shipping_address="123 Nguyen Trai, District 1, HCMC",
        created_at=created,
        updated_at=created,
    )
    session.add(order)
    await session.flush()

    for item in items:
        session.add(
            OrderItem(
                order_id=order.id,
                plant_id=item.plant.id,
                plant_name=item.plant_name or item.plant.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                created_at=created,
                updated_at=created,
            )
        )

    await session.commit()
    await session.refresh(order)
    return order


def _month_start(moment: datetime) -> datetime:
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day(entry: dict) -> date:
    return date.fromisoformat(entry["date"])


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(OVERVIEW_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_overview_inactive_admin_cannot_log_in(
    client: AsyncClient,
    inactive_admin: Admin,
) -> None:
    login = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": inactive_admin.email, "password": "correct-password"},
    )
    assert login.status_code == 401

    response = await client.get(OVERVIEW_PATH)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_overview_rejects_admin_deactivated_after_login(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    assert (await client.get(OVERVIEW_PATH)).status_code == 200

    active_admin.is_active = False
    test_db_session.add(active_admin)
    await test_db_session.commit()

    response = await client.get(OVERVIEW_PATH)
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Empty shop
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_on_empty_database(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    body = await _overview(client)

    assert body["summary"] == {
        "total_plants": 0,
        "active_plants": 0,
        "total_categories": 0,
        "active_categories": 0,
        "total_customers": 0,
        "active_customers": 0,
        "total_orders": 0,
        "pending_orders": 0,
        "total_revenue": "0.00",
    }
    assert body["sales"]["today"] == {"orders": 0, "revenue": "0.00"}
    assert body["sales"]["this_month"] == {"orders": 0, "revenue": "0.00"}
    assert body["orders_by_status"] == {
        "pending": 0,
        "confirmed": 0,
        "processing": 0,
        "shipping": 0,
        "completed": 0,
        "cancelled": 0,
    }
    assert body["top_plants"] == []
    assert body["low_stock"] == []
    assert body["recent_orders"] == []

    today = datetime.now(UTC).date()
    assert len(body["revenue_by_day"]) == today.day
    assert all(entry["revenue"] == "0.00" for entry in body["revenue_by_day"])
    assert _day(body["revenue_by_day"][0]) == today.replace(day=1)
    assert _day(body["revenue_by_day"][-1]) == today


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_counts_all_entities(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)

    active_category = await _seed_category(test_db_session)
    await _seed_category(test_db_session, is_active=False)

    await _seed_plant(test_db_session, active_category)
    await _seed_plant(test_db_session, active_category)
    await _seed_plant(test_db_session, active_category, is_active=False)

    customer = await _seed_customer(test_db_session)
    await _seed_customer(test_db_session)
    await _seed_customer(test_db_session, is_active=False)

    await _seed_order(test_db_session, customer, status=OrderStatus.PENDING)
    await _seed_order(test_db_session, customer, status=OrderStatus.PENDING)
    await _seed_order(test_db_session, customer, status=OrderStatus.CONFIRMED)
    await _seed_order(test_db_session, customer, status=OrderStatus.COMPLETED)

    summary = (await _overview(client))["summary"]

    assert summary["total_plants"] == 3
    assert summary["active_plants"] == 2
    assert summary["total_categories"] == 2
    assert summary["active_categories"] == 1
    assert summary["total_customers"] == 3
    assert summary["active_customers"] == 2
    assert summary["total_orders"] == 4
    assert summary["pending_orders"] == 2


# --------------------------------------------------------------------------
# Revenue
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_total_revenue_counts_completed_orders_only(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)

    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("500000.00"),
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("250000.50"),
    )
    for ignored in (
        OrderStatus.PENDING,
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.SHIPPING,
        OrderStatus.CANCELLED,
    ):
        await _seed_order(
            test_db_session,
            customer,
            status=ignored,
            total_amount=Decimal("999000.00"),
        )

    summary = (await _overview(client))["summary"]

    assert summary["total_revenue"] == "750000.50"
    assert summary["total_orders"] == 7


@pytest.mark.asyncio
async def test_total_revenue_is_zero_without_completed_orders(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.CANCELLED,
        total_amount=Decimal("400000.00"),
    )

    summary = (await _overview(client))["summary"]

    assert summary["total_revenue"] == "0.00"


@pytest.mark.asyncio
async def test_today_sales_exclude_older_and_uncompleted_orders(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)
    now = datetime.now(UTC)

    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("1200000.00"),
        created_at=now,
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.PENDING,
        total_amount=Decimal("300000.00"),
        created_at=now,
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("900000.00"),
        created_at=now - timedelta(days=1),
    )

    today = (await _overview(client))["sales"]["today"]

    # Both of today's orders are counted; only the completed one earns money.
    assert today["orders"] == 2
    assert today["revenue"] == "1200000.00"


@pytest.mark.asyncio
async def test_this_month_sales_exclude_previous_month(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)
    now = datetime.now(UTC)
    last_month = _month_start(now) - timedelta(days=1)

    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("1000000.00"),
        created_at=now,
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.CANCELLED,
        total_amount=Decimal("700000.00"),
        created_at=now,
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("5000000.00"),
        created_at=last_month,
    )

    body = await _overview(client)

    assert body["sales"]["this_month"] == {"orders": 2, "revenue": "1000000.00"}
    # Lifetime revenue still includes last month.
    assert body["summary"]["total_revenue"] == "6000000.00"


# --------------------------------------------------------------------------
# Orders by status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orders_by_status_returns_every_status(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)

    await _seed_order(test_db_session, customer, status=OrderStatus.PENDING)
    await _seed_order(test_db_session, customer, status=OrderStatus.PENDING)
    await _seed_order(test_db_session, customer, status=OrderStatus.COMPLETED)
    await _seed_order(test_db_session, customer, status=OrderStatus.CANCELLED)

    orders_by_status = (await _overview(client))["orders_by_status"]

    assert orders_by_status == {
        "pending": 2,
        "confirmed": 0,
        "processing": 0,
        "shipping": 0,
        "completed": 1,
        "cancelled": 1,
    }


# --------------------------------------------------------------------------
# Revenue by day
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revenue_by_day_aggregates_the_current_month(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)
    now = datetime.now(UTC)
    first_of_month = _month_start(now) + timedelta(hours=12)

    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("400000.00"),
        created_at=now,
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("100000.00"),
        created_at=now,
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.PENDING,
        total_amount=Decimal("800000.00"),
        created_at=now,
    )
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("250000.00"),
        created_at=first_of_month,
    )
    # Last month must not leak into the series.
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("9000000.00"),
        created_at=_month_start(now) - timedelta(days=2),
    )

    series = (await _overview(client))["revenue_by_day"]
    today = now.date()
    by_day = {_day(entry): entry for entry in series}

    # One chronological, gap-free entry per day from the 1st up to today.
    assert [_day(entry) for entry in series] == sorted(by_day)
    assert len(series) == today.day
    assert _day(series[0]) == today.replace(day=1)
    assert _day(series[-1]) == today

    if today.day == 1:
        # Everything seeded this month landed on the same (first) day.
        assert by_day[today] == {
            "date": today.isoformat(),
            "orders": 4,
            "revenue": "750000.00",
        }
    else:
        assert by_day[today] == {
            "date": today.isoformat(),
            "orders": 3,
            "revenue": "500000.00",
        }
        assert by_day[first_of_month.date()] == {
            "date": first_of_month.date().isoformat(),
            "orders": 1,
            "revenue": "250000.00",
        }
        # Days without sales are still part of the chart.
        quiet_days = [
            entry
            for entry in series
            if _day(entry) not in {today, first_of_month.date()}
        ]
        assert all(
            entry["orders"] == 0 and entry["revenue"] == "0.00"
            for entry in quiet_days
        )


# --------------------------------------------------------------------------
# Top plants
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_top_plants_ranks_completed_sales_only(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    category = await _seed_category(test_db_session)
    customer = await _seed_customer(test_db_session)

    # Six plants sold 6, 5, 4, 3, 2 and 1 times: the last one falls off the top 5.
    plants = [await _seed_plant(test_db_session, category) for _ in range(6)]
    for index, plant in enumerate(plants):
        quantity = 6 - index
        await _seed_order(
            test_db_session,
            customer,
            status=OrderStatus.COMPLETED,
            total_amount=Decimal("100000.00") * quantity,
            items=(_Item(plant=plant, quantity=quantity, unit_price=Decimal("100000.00")),),
        )

    # A second completed order adds to the runner-up without overtaking the top.
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("50000.00"),
        items=(_Item(plant=plants[1], quantity=1, unit_price=Decimal("50000.00")),),
    )
    # Unfinished orders never make a plant a best seller.
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.PENDING,
        total_amount=Decimal("9900000.00"),
        items=(_Item(plant=plants[5], quantity=99, unit_price=Decimal("100000.00")),),
    )

    top_plants = (await _overview(client))["top_plants"]

    assert len(top_plants) == 5
    assert [item["quantity_sold"] for item in top_plants] == [6, 6, 4, 3, 2]
    assert [item["plant_id"] for item in top_plants[:2]] == [
        str(plants[0].id),
        str(plants[1].id),
    ]
    # Ties break on revenue: 6 × 100000 beats 5 × 100000 + 1 × 50000.
    assert top_plants[0]["revenue"] == "600000.00"
    assert top_plants[1]["revenue"] == "550000.00"
    assert str(plants[5].id) not in {item["plant_id"] for item in top_plants}


@pytest.mark.asyncio
async def test_top_plants_use_the_order_item_snapshot_name(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    category = await _seed_category(test_db_session)
    customer = await _seed_customer(test_db_session)
    plant = await _seed_plant(test_db_session, category, name="Monstera Deliciosa")

    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("600000.00"),
        items=(
            _Item(
                plant=plant,
                quantity=2,
                unit_price=Decimal("300000.00"),
                plant_name="Monstera Deliciosa",
            ),
        ),
    )

    plant.name = "Renamed After The Sale"
    test_db_session.add(plant)
    await test_db_session.commit()

    top_plants = (await _overview(client))["top_plants"]

    assert top_plants[0]["plant_name"] == "Monstera Deliciosa"
    assert top_plants[0]["quantity_sold"] == 2
    assert top_plants[0]["revenue"] == "600000.00"


# --------------------------------------------------------------------------
# Low stock
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_stock_lists_scarce_active_plants_only(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    category = await _seed_category(test_db_session)

    for stock in (5, 4, 3, 2, 1, 0):
        await _seed_plant(test_db_session, category, stock=stock)
    # Above the threshold, and a scarce plant that is no longer on sale.
    await _seed_plant(test_db_session, category, stock=6)
    inactive = await _seed_plant(
        test_db_session,
        category,
        stock=1,
        is_active=False,
    )

    low_stock = (await _overview(client))["low_stock"]

    assert len(low_stock) == 5
    assert [item["stock"] for item in low_stock] == [0, 1, 2, 3, 4]
    assert str(inactive.id) not in {item["plant_id"] for item in low_stock}


@pytest.mark.asyncio
async def test_low_stock_includes_the_threshold(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    category = await _seed_category(test_db_session)
    at_threshold = await _seed_plant(test_db_session, category, stock=5)
    await _seed_plant(test_db_session, category, stock=6)

    low_stock = (await _overview(client))["low_stock"]

    assert [item["plant_id"] for item in low_stock] == [str(at_threshold.id)]
    assert low_stock[0]["stock"] == 5
    assert low_stock[0]["plant_name"] == at_threshold.name


# --------------------------------------------------------------------------
# Recent orders
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_orders_returns_five_newest_with_customer(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session, name="Nguyen Van A")
    now = datetime.now(UTC)

    orders = [
        await _seed_order(
            test_db_session,
            customer,
            status=OrderStatus.PENDING,
            total_amount=Decimal("850000.00"),
            created_at=now - timedelta(minutes=index),
        )
        for index in range(6)
    ]

    recent = (await _overview(client))["recent_orders"]

    assert len(recent) == 5
    assert [item["id"] for item in recent] == [str(order.id) for order in orders[:5]]
    assert [item["created_at"] for item in recent] == sorted(
        (item["created_at"] for item in recent), reverse=True
    )

    newest = recent[0]
    assert newest["order_number"] == orders[0].order_number
    assert newest["customer_name"] == customer.name
    assert newest["customer_phone"] == customer.phone
    assert newest["status"] == "pending"
    assert newest["total_amount"] == "850000.00"


# --------------------------------------------------------------------------
# Serialization, timezone and query count
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_money_is_serialized_as_fixed_scale_decimal(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    category = await _seed_category(test_db_session)
    customer = await _seed_customer(test_db_session)
    plant = await _seed_plant(test_db_session, category, stock=2)
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("123456.70"),
        items=(_Item(plant=plant, quantity=1, unit_price=Decimal("123456.70")),),
    )

    body = await _overview(client)

    monetary = [
        body["summary"]["total_revenue"],
        body["sales"]["today"]["revenue"],
        body["sales"]["this_month"]["revenue"],
        body["top_plants"][0]["revenue"],
        body["recent_orders"][0]["total_amount"],
        *(entry["revenue"] for entry in body["revenue_by_day"]),
    ]
    assert all(isinstance(value, str) for value in monetary)
    assert all(MONEY_PATTERN.match(value) for value in monetary)


@pytest.mark.asyncio
async def test_days_are_cut_in_utc_not_server_local_time(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    """An order just after midnight UTC belongs to the new UTC day."""
    await _login(client, active_admin)
    customer = await _seed_customer(test_db_session)
    now = datetime.now(UTC)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("200000.00"),
        created_at=start_of_today,
    )
    # One second before midnight UTC still belongs to the previous day.
    await _seed_order(
        test_db_session,
        customer,
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("700000.00"),
        created_at=start_of_today - timedelta(seconds=1),
    )

    body = await _overview(client)
    series = {_day(entry): entry for entry in body["revenue_by_day"]}

    assert body["sales"]["today"] == {"orders": 1, "revenue": "200000.00"}
    assert series[now.date()]["orders"] == 1
    assert series[now.date()]["revenue"] == "200000.00"


@pytest.mark.asyncio
async def test_overview_uses_a_fixed_number_of_queries(
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    """The dashboard aggregates in SQL: more data must not mean more queries."""
    category = await _seed_category(test_db_session)
    customer = await _seed_customer(test_db_session)
    for _ in range(5):
        plant = await _seed_plant(test_db_session, category, stock=1)
        await _seed_order(
            test_db_session,
            customer,
            status=OrderStatus.COMPLETED,
            total_amount=Decimal("100000.00"),
            items=(_Item(plant=plant, quantity=2, unit_price=Decimal("50000.00")),),
        )

    test_db_session.expunge_all()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        stats = await build_overview(test_db_session)
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

    # summary + sales + statuses + daily series + top plants + low stock + recent
    assert len(statements) == 7
    assert stats.summary.total_orders == 5
    assert len(stats.recent_orders) == 5
    assert len(stats.top_plants) == 5
    assert len(stats.low_stock) == 5
