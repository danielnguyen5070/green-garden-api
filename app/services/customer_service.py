"""Customer business logic.

Customers are guests identified by a unique phone number: no passwords, no
login and no hard delete — `is_active` is the only way to retire one, which
keeps their order history intact.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.models.customer import Customer


class CustomerNotFoundError(Exception):
    """Raised when a customer id does not exist."""


class CustomerPhoneConflictError(Exception):
    """Raised when a phone number is already used by another customer."""


class CustomerInactiveError(Exception):
    """Raised when a deactivated customer is used for a new order."""


def _base_options() -> tuple[Any, ...]:
    """Customer rows never need their order history loaded."""
    return (noload(Customer.orders),)


async def _ensure_phone_available(
    session: AsyncSession,
    phone: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(Customer.id).where(Customer.phone == phone)
    if exclude_id is not None:
        stmt = stmt.where(Customer.id != exclude_id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise CustomerPhoneConflictError(f"Customer with phone '{phone}' already exists")


def _apply_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    is_active: bool | None,
) -> Select[Any]:
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Customer.phone.ilike(pattern),
                Customer.name.ilike(pattern),
                Customer.email.ilike(pattern),
            )
        )
    if is_active is not None:
        stmt = stmt.where(Customer.is_active.is_(is_active))
    return stmt


async def list_customers(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[Customer], int]:
    """Newest customers first, matching the other admin listings."""
    filters = {"search": search, "is_active": is_active}

    count_stmt = _apply_filters(select(func.count()).select_from(Customer), **filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = _apply_filters(select(Customer), **filters)
    stmt = (
        stmt.options(*_base_options())
        .order_by(Customer.created_at.desc(), Customer.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_customer(session: AsyncSession, customer_id: uuid.UUID) -> Customer:
    result = await session.execute(
        select(Customer).where(Customer.id == customer_id).options(*_base_options())
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise CustomerNotFoundError("Customer not found")
    return customer


async def get_customer_by_phone(
    session: AsyncSession,
    phone: str,
) -> Customer | None:
    result = await session.execute(
        select(Customer).where(Customer.phone == phone).options(*_base_options())
    )
    return result.scalar_one_or_none()


async def create_customer(
    session: AsyncSession,
    *,
    phone: str,
    name: str,
    email: str | None,
) -> Customer:
    await _ensure_phone_available(session, phone)

    customer = Customer(phone=phone, name=name, email=email, is_active=True)
    session.add(customer)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_customer(session, customer.id)


async def update_customer(
    session: AsyncSession,
    customer_id: uuid.UUID,
    *,
    phone: str | None = None,
    name: str | None = None,
    email: str | None = None,
    email_provided: bool = False,
) -> Customer:
    """Identity fields only — order history and timestamps are never touched."""
    customer = await get_customer(session, customer_id)

    if phone is not None and phone != customer.phone:
        await _ensure_phone_available(session, phone, exclude_id=customer.id)
        customer.phone = phone

    if name is not None:
        customer.name = name
    if email_provided:
        customer.email = email

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_customer(session, customer.id)


async def set_customer_status(
    session: AsyncSession,
    customer_id: uuid.UUID,
    *,
    is_active: bool,
) -> Customer:
    """Soft deactivation: the row and its orders always stay in place."""
    customer = await get_customer(session, customer_id)
    customer.is_active = is_active
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_customer(session, customer.id)


async def resolve_customer_for_order(
    session: AsyncSession,
    *,
    phone: str,
    name: str,
    email: str | None,
) -> Customer:
    """
    Find the customer behind a checkout phone number, creating one when new.

    Never commits — the caller owns the order transaction. An existing profile
    keeps the name it already has; a missing email is filled in so the shop can
    reach the customer about this order.
    """
    customer = await get_customer_by_phone(session, phone)
    if customer is not None:
        if not customer.is_active:
            raise CustomerInactiveError(
                f"Customer with phone '{phone}' is inactive and cannot place orders"
            )
        if email is not None and customer.email is None:
            customer.email = email
        return customer

    customer = Customer(phone=phone, name=name, email=email, is_active=True)
    session.add(customer)
    await session.flush()
    return customer
