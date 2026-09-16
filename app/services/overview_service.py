"""Admin dashboard statistics, aggregated by PostgreSQL.

Every number comes out of SQL (`COUNT`, `SUM`, `GROUP BY`, `ORDER BY`,
`LIMIT`): no table is ever loaded into Python to be summed, so the endpoint
costs a fixed, small number of queries no matter how large the shop grows.
Nothing is cached — each call reads the current state of the eight existing
tables.

Two rules decide what the numbers mean:

* **Revenue is `completed` orders only.** `pending`, `confirmed`, `processing`,
  `shipping` and `cancelled` orders are counted, but never earn money. Missing
  revenue is `0.00`, never `null`.
* **Days and months are cut in UTC**, the timezone the application stores and
  filters every timestamp in, so the dashboard never drifts with the server's
  local time.

Top sellers are named from the `order_items` snapshot rather than the current
plant, so renaming or deleting a plant cannot rewrite past sales.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, String, cast, func, select
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.plant import Plant

# A plant is "low stock" at this many units or fewer.
LOW_STOCK_THRESHOLD = 5
TOP_PLANTS_LIMIT = 5
LOW_STOCK_LIMIT = 5
RECENT_ORDERS_LIMIT = 5

_MONEY_QUANTUM = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class SummaryStats:
    total_plants: int
    active_plants: int
    total_categories: int
    active_categories: int
    total_customers: int
    active_customers: int
    total_orders: int
    pending_orders: int
    total_revenue: Decimal


@dataclass(frozen=True)
class PeriodStats:
    orders: int
    revenue: Decimal


@dataclass(frozen=True)
class SalesStats:
    today: PeriodStats
    this_month: PeriodStats


@dataclass(frozen=True)
class DayStats:
    date: date
    orders: int
    revenue: Decimal


@dataclass(frozen=True)
class TopPlantStats:
    plant_id: uuid.UUID
    plant_name: str
    quantity_sold: int
    revenue: Decimal


@dataclass(frozen=True)
class LowStockStats:
    plant_id: uuid.UUID
    plant_name: str
    stock: int


@dataclass(frozen=True)
class RecentOrderStats:
    id: uuid.UUID
    order_number: str
    customer_name: str | None
    customer_phone: str | None
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime


@dataclass(frozen=True)
class OverviewStats:
    summary: SummaryStats
    sales: SalesStats
    orders_by_status: dict[str, int]
    revenue_by_day: list[DayStats]
    top_plants: list[TopPlantStats]
    low_stock: list[LowStockStats]
    recent_orders: list[RecentOrderStats]


def _money(value: Decimal | int | None) -> Decimal:
    """Money is never `null` on the dashboard: an empty sum reads as `0.00`."""
    if value is None:
        return _ZERO
    return Decimal(value).quantize(_MONEY_QUANTUM)


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _start_of_next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _count(entity: Any, *criteria: Any) -> Any:
    stmt = select(func.count()).select_from(entity)
    if criteria:
        stmt = stmt.where(*criteria)
    return stmt.scalar_subquery()


def _completed_revenue(*criteria: Any) -> Any:
    stmt = select(func.coalesce(func.sum(Order.total_amount), 0)).where(
        Order.status == OrderStatus.COMPLETED,
        *criteria,
    )
    return stmt.scalar_subquery()


def _utc_day(column: Any) -> Any:
    """Calendar day of a `timestamptz`, always cut in UTC."""
    return cast(func.timezone("UTC", column), Date)


async def _load_summary(session: AsyncSession) -> SummaryStats:
    """All header counters plus lifetime revenue in a single round trip."""
    row = (
        await session.execute(
            select(
                _count(Plant),
                _count(Plant, Plant.is_active.is_(True)),
                _count(Category),
                _count(Category, Category.is_active.is_(True)),
                _count(Customer),
                _count(Customer, Customer.is_active.is_(True)),
                _count(Order),
                _count(Order, Order.status == OrderStatus.PENDING),
                _completed_revenue(),
            )
        )
    ).one()

    return SummaryStats(
        total_plants=int(row[0]),
        active_plants=int(row[1]),
        total_categories=int(row[2]),
        active_categories=int(row[3]),
        total_customers=int(row[4]),
        active_customers=int(row[5]),
        total_orders=int(row[6]),
        pending_orders=int(row[7]),
        total_revenue=_money(row[8]),
    )


async def _load_sales(
    session: AsyncSession,
    *,
    day_start: datetime,
    day_end: datetime,
    month_start: datetime,
    month_end: datetime,
) -> SalesStats:
    """
    Today and the current month from one scan of this month's orders.

    Today always falls inside the current month, so both periods are filtered
    out of the same rows with `FILTER` instead of querying the table twice.
    """
    today_window = (Order.created_at >= day_start, Order.created_at < day_end)
    row = (
        await session.execute(
            select(
                func.count().filter(*today_window),
                func.coalesce(
                    func.sum(Order.total_amount).filter(
                        Order.status == OrderStatus.COMPLETED,
                        *today_window,
                    ),
                    0,
                ),
                func.count(),
                func.coalesce(
                    func.sum(Order.total_amount).filter(
                        Order.status == OrderStatus.COMPLETED
                    ),
                    0,
                ),
            )
            .select_from(Order)
            .where(Order.created_at >= month_start, Order.created_at < month_end)
        )
    ).one()

    return SalesStats(
        today=PeriodStats(orders=int(row[0]), revenue=_money(row[1])),
        this_month=PeriodStats(orders=int(row[2]), revenue=_money(row[3])),
    )


async def _load_orders_by_status(session: AsyncSession) -> dict[str, int]:
    """Counts for all six statuses — the unused ones report `0`."""
    result = await session.execute(
        select(Order.status, func.count()).group_by(Order.status)
    )
    counts = {status.value: 0 for status in OrderStatus}
    for status, count in result.all():
        counts[status.value] = int(count)
    return counts


async def _load_revenue_by_day(
    session: AsyncSession,
    *,
    month_start: datetime,
    day_end: datetime,
    first_day: date,
    today: date,
) -> list[DayStats]:
    """
    Month-to-date daily series, chronological and gap-free.

    Postgres only returns the days that actually have orders, so the quiet days
    are filled in here with zeros — the chart needs a point for every day.
    """
    day = _utc_day(Order.created_at).label("day")
    result = await session.execute(
        select(
            day,
            func.count(),
            func.coalesce(
                func.sum(Order.total_amount).filter(
                    Order.status == OrderStatus.COMPLETED
                ),
                0,
            ),
        )
        .select_from(Order)
        .where(Order.created_at >= month_start, Order.created_at < day_end)
        .group_by(day)
    )
    by_day = {row[0]: (int(row[1]), _money(row[2])) for row in result.all()}

    series: list[DayStats] = []
    current = first_day
    while current <= today:
        orders, revenue = by_day.get(current, (0, _ZERO))
        series.append(DayStats(date=current, orders=orders, revenue=revenue))
        current += timedelta(days=1)
    return series


async def _load_top_plants(session: AsyncSession) -> list[TopPlantStats]:
    """
    Best sellers across completed orders, grouped in SQL.

    The display name is the snapshot from the most recent sale, not the current
    plant name, so historical sales keep reading the way they were sold.
    """
    quantity_sold = func.sum(OrderItem.quantity).label("quantity_sold")
    revenue = func.sum(OrderItem.quantity * OrderItem.unit_price).label("revenue")
    latest_name = func.array_agg(
        aggregate_order_by(
            OrderItem.plant_name,
            Order.created_at.desc(),
            OrderItem.created_at.desc(),
        ),
        type_=ARRAY(String),
    )[1].label("plant_name")

    result = await session.execute(
        select(OrderItem.plant_id, latest_name, quantity_sold, revenue)
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.status == OrderStatus.COMPLETED)
        .group_by(OrderItem.plant_id)
        .order_by(quantity_sold.desc(), revenue.desc())
        .limit(TOP_PLANTS_LIMIT)
    )
    return [
        TopPlantStats(
            plant_id=row[0],
            plant_name=row[1],
            quantity_sold=int(row[2]),
            revenue=_money(row[3]),
        )
        for row in result.all()
    ]


async def _load_low_stock(session: AsyncSession) -> list[LowStockStats]:
    """Active plants that are about to run out, scarcest first."""
    result = await session.execute(
        select(Plant.id, Plant.name, Plant.stock)
        .where(Plant.is_active.is_(True), Plant.stock <= LOW_STOCK_THRESHOLD)
        .order_by(Plant.stock.asc(), Plant.name.asc())
        .limit(LOW_STOCK_LIMIT)
    )
    return [
        LowStockStats(plant_id=row[0], plant_name=row[1], stock=int(row[2]))
        for row in result.all()
    ]


async def _load_recent_orders(session: AsyncSession) -> list[RecentOrderStats]:
    """
    Newest orders with their customer joined in one query.

    The join is an outer join and the customer fields are optional: an order
    whose customer row somehow went missing still shows up on the dashboard
    instead of failing the whole overview.
    """
    result = await session.execute(
        select(
            Order.id,
            Order.order_number,
            Order.status,
            Order.total_amount,
            Order.created_at,
            Customer.name,
            Customer.phone,
        )
        .outerjoin(Customer, Order.customer_id == Customer.id)
        .order_by(Order.created_at.desc(), Order.id)
        .limit(RECENT_ORDERS_LIMIT)
    )
    return [
        RecentOrderStats(
            id=row[0],
            order_number=row[1],
            status=row[2],
            total_amount=_money(row[3]),
            created_at=row[4],
            customer_name=row[5],
            customer_phone=row[6],
        )
        for row in result.all()
    ]


async def build_overview(session: AsyncSession) -> OverviewStats:
    """Collect every dashboard statistic for the current UTC day and month."""
    today = datetime.now(UTC).date()
    first_day = today.replace(day=1)

    day_start = _start_of_day(today)
    day_end = _start_of_day(today + timedelta(days=1))
    month_start = _start_of_day(first_day)
    month_end = _start_of_day(_start_of_next_month(today))

    return OverviewStats(
        summary=await _load_summary(session),
        sales=await _load_sales(
            session,
            day_start=day_start,
            day_end=day_end,
            month_start=month_start,
            month_end=month_end,
        ),
        orders_by_status=await _load_orders_by_status(session),
        revenue_by_day=await _load_revenue_by_day(
            session,
            month_start=month_start,
            day_end=day_end,
            first_day=first_day,
            today=today,
        ),
        top_plants=await _load_top_plants(session),
        low_stock=await _load_low_stock(session),
        recent_orders=await _load_recent_orders(session),
    )
