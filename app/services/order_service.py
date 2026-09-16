"""Order business logic: pricing, stock movements and status transitions.

Money is always `Decimal` / `NUMERIC(12,2)`. Prices come from the database, never
from the request: an order item stores the plant name and the calculated unit
price as a snapshot so the order stays historically correct after the plant is
renamed, repriced or deactivated.

Creating an order (customer upsert, order, items and stock deduction) happens in
a single transaction, and stock is deducted with `SELECT ... FOR UPDATE` so two
concurrent checkouts cannot oversell the same plant.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, NamedTuple, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.plant import Plant
from app.models.plant_pot_size import PlantPotSize
from app.services.customer_service import resolve_customer_for_order
from app.services.plant_service import PlantNotFoundError

_ORDER_NUMBER_PREFIX = "GG"
# Shared advisory lock key so concurrent checkouts allocate order numbers
# one at a time instead of racing for the same daily sequence.
_ORDER_NUMBER_LOCK_KEY = 20260916
_MONEY_QUANTUM = Decimal("0.01")
_MAX_TOTAL_AMOUNT = Decimal("9999999999.99")

# Forward-only pipeline; cancellation is allowed from any non-terminal status.
_STATUS_FLOW: tuple[OrderStatus, ...] = (
    OrderStatus.PENDING,
    OrderStatus.CONFIRMED,
    OrderStatus.PROCESSING,
    OrderStatus.SHIPPING,
    OrderStatus.COMPLETED,
)
_TERMINAL_STATUSES = frozenset({OrderStatus.COMPLETED, OrderStatus.CANCELLED})


class OrderNotFoundError(Exception):
    """Raised when an order id does not exist."""


class PlantUnavailableError(Exception):
    """Raised when a plant is inactive or the pot size cannot be ordered."""


class InsufficientStockError(Exception):
    """Raised when the ordered quantity exceeds the available stock."""


class InvalidStatusTransitionError(Exception):
    """Raised when a status change is not allowed for the current status."""


class OrderTotalTooLargeError(Exception):
    """Raised when the calculated total does not fit `NUMERIC(12,2)`."""


class OrderItemInput(NamedTuple):
    """One requested line: what to buy, how many and in which pot size."""

    plant_id: uuid.UUID
    quantity: int
    pot_size: str | None


def _detail_options() -> tuple[Any, ...]:
    """Eager-load customer and items; never walk back to orders or plants."""
    return (
        selectinload(Order.customer).noload(Customer.orders),
        selectinload(Order.items).noload(OrderItem.plant),
    )


def _plant_options() -> tuple[Any, ...]:
    """Stock updates only touch the plant row itself."""
    return (
        noload(Plant.category),
        noload(Plant.images),
        noload(Plant.pot_sizes),
        noload(Plant.order_items),
    )


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(_MONEY_QUANTUM)


async def _generate_order_number(session: AsyncSession) -> str:
    """Allocate the next `GG-YYYYMMDD-NNNN` for today, serialized by a lock."""
    prefix = f"{_ORDER_NUMBER_PREFIX}-{datetime.now(UTC).strftime('%Y%m%d')}-"
    await session.execute(select(func.pg_advisory_xact_lock(_ORDER_NUMBER_LOCK_KEY)))
    result = await session.execute(
        select(Order.order_number).where(Order.order_number.like(f"{prefix}%"))
    )
    taken = set(result.scalars().all())

    sequence = len(taken) + 1
    while f"{prefix}{sequence:04d}" in taken:
        sequence += 1
    return f"{prefix}{sequence:04d}"


async def _lock_plants(
    session: AsyncSession,
    plant_ids: set[uuid.UUID],
) -> dict[uuid.UUID, Plant]:
    result = await session.execute(
        select(Plant)
        .where(Plant.id.in_(plant_ids))
        .options(*_plant_options())
        .order_by(Plant.id)
        .with_for_update()
    )
    return {plant.id: plant for plant in result.scalars().all()}


async def _load_pot_sizes(
    session: AsyncSession,
    plant_ids: set[uuid.UUID],
) -> dict[tuple[uuid.UUID, str], PlantPotSize]:
    """Active pot sizes keyed by plant and lowercased name."""
    result = await session.execute(
        select(PlantPotSize)
        .where(
            PlantPotSize.plant_id.in_(plant_ids),
            PlantPotSize.is_active.is_(True),
        )
        .options(noload(PlantPotSize.plant))
    )
    return {
        (pot_size.plant_id, pot_size.name.lower()): pot_size
        for pot_size in result.scalars().all()
    }


def _apply_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    status: OrderStatus | None,
    customer_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> Select[Any]:
    if search:
        pattern = f"%{search.strip()}%"
        # Join instead of a subquery per row so searching stays a single query.
        stmt = stmt.join(Customer, Order.customer_id == Customer.id).where(
            or_(
                Order.order_number.ilike(pattern),
                Customer.phone.ilike(pattern),
                Customer.name.ilike(pattern),
            )
        )
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if customer_id is not None:
        stmt = stmt.where(Order.customer_id == customer_id)
    if date_from is not None:
        stmt = stmt.where(
            Order.created_at >= datetime.combine(date_from, time.min, tzinfo=UTC)
        )
    if date_to is not None:
        # `date_to` is inclusive: everything before the next day starts.
        stmt = stmt.where(
            Order.created_at
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    return stmt


async def list_orders(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    status: OrderStatus | None = None,
    customer_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[Order], int]:
    """Newest orders first, with customer and items eager-loaded."""
    filters = {
        "search": search,
        "status": status,
        "customer_id": customer_id,
        "date_from": date_from,
        "date_to": date_to,
    }

    count_stmt = _apply_filters(select(func.count()).select_from(Order), **filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = _apply_filters(select(Order), **filters)
    stmt = (
        stmt.options(*_detail_options())
        .order_by(Order.created_at.desc(), Order.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    result = await session.execute(
        select(Order).where(Order.id == order_id).options(*_detail_options())
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise OrderNotFoundError("Order not found")
    return order


async def create_order(
    session: AsyncSession,
    *,
    customer_phone: str,
    customer_name: str,
    customer_email: str | None,
    shipping_address: str,
    note: str | None,
    items: Sequence[OrderItemInput],
) -> Order:
    """
    Create an order from the current catalogue state in one transaction.

    Customer upsert, order, item snapshots and stock deduction are committed
    together, so a rejected line (unknown/inactive plant, unusable pot size,
    insufficient stock) leaves no partial order and no stock movement behind.
    """
    try:
        customer = await resolve_customer_for_order(
            session,
            phone=customer_phone,
            name=customer_name,
            email=customer_email,
        )

        plant_ids = {item.plant_id for item in items}
        plants = await _lock_plants(session, plant_ids)
        if plant_ids - plants.keys():
            raise PlantNotFoundError("Plant not found")
        pot_sizes = await _load_pot_sizes(session, plant_ids)

        # Sum per plant first: the same plant may appear on several lines
        # (different pot sizes) and must not oversell across them.
        requested: dict[uuid.UUID, int] = defaultdict(int)
        for item in items:
            requested[item.plant_id] += item.quantity

        for plant_id, quantity in requested.items():
            plant = plants[plant_id]
            if not plant.is_active:
                raise PlantUnavailableError(f"Plant '{plant.name}' is not available")
            if plant.stock < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock for plant '{plant.name}': "
                    f"requested {quantity}, available {plant.stock}"
                )

        total_amount = Decimal("0.00")
        lines: list[tuple[Plant, OrderItemInput, str | None, Decimal]] = []
        for item in items:
            plant = plants[item.plant_id]
            pot_size_name: str | None = None
            adjustment = Decimal("0.00")
            if item.pot_size is not None:
                pot_size = pot_sizes.get((plant.id, item.pot_size.lower()))
                if pot_size is None:
                    raise PlantUnavailableError(
                        f"Pot size '{item.pot_size}' is not available "
                        f"for plant '{plant.name}'"
                    )
                pot_size_name = pot_size.name
                adjustment = pot_size.price_adjustment

            unit_price = _quantize(plant.price + adjustment)
            total_amount += unit_price * item.quantity
            lines.append((plant, item, pot_size_name, unit_price))

        total_amount = _quantize(total_amount)
        if total_amount > _MAX_TOTAL_AMOUNT:
            raise OrderTotalTooLargeError("Order total is too large to be processed")

        order = Order(
            customer_id=customer.id,
            order_number=await _generate_order_number(session),
            status=OrderStatus.PENDING,
            total_amount=total_amount,
            shipping_address=shipping_address,
            note=note,
        )
        session.add(order)
        await session.flush()

        session.add_all(
            [
                OrderItem(
                    order_id=order.id,
                    plant_id=plant.id,
                    plant_name=plant.name,
                    quantity=item.quantity,
                    unit_price=unit_price,
                    pot_size=pot_size_name,
                )
                for plant, item, pot_size_name, unit_price in lines
            ]
        )

        for plant_id, quantity in requested.items():
            plants[plant_id].stock -= quantity

        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_order(session, order.id)


def _ensure_transition_allowed(current: OrderStatus, target: OrderStatus) -> None:
    if current in _TERMINAL_STATUSES:
        raise InvalidStatusTransitionError(
            f"Order is already {current.value} and cannot change status"
        )
    if target is OrderStatus.CANCELLED:
        return
    if _STATUS_FLOW.index(target) < _STATUS_FLOW.index(current):
        raise InvalidStatusTransitionError(
            f"Cannot change order status from '{current.value}' to '{target.value}'"
        )


async def _restore_stock(session: AsyncSession, order: Order) -> None:
    """
    Give the ordered quantities back to the plants.

    Stock is deducted once when the order is created and only ever returned on
    the transition into `cancelled`. Because `cancelled` is terminal and
    re-sending the same status is a no-op, an order can never be restocked twice.
    """
    quantities: dict[uuid.UUID, int] = defaultdict(int)
    for item in order.items:
        quantities[item.plant_id] += item.quantity
    if not quantities:
        return

    plants = await _lock_plants(session, set(quantities))
    for plant_id, quantity in quantities.items():
        plant = plants.get(plant_id)
        if plant is not None:
            plant.stock += quantity


async def update_order_status(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    status: OrderStatus,
) -> Order:
    """Move an order along the pipeline, restocking on cancellation."""
    order = await get_order(session, order_id)
    if status is order.status:
        # Nothing to change: never touch stock or any other order data.
        return order

    _ensure_transition_allowed(order.status, status)

    try:
        # Restock and the status change commit together, so a cancelled order can
        # never be left with the stock still deducted.
        if status is OrderStatus.CANCELLED:
            await _restore_stock(session, order)
        order.status = status
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_order(session, order.id)
