"""Storefront bot protection tests: honeypot, fill time and checkout phone limit."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.categories.models import Category
from app.features.customers.models import Customer
from app.features.orders.models import Order
from app.features.plants.models import Plant
from app.features.reviews.models import Review
from app.shared.bot_protection.schemas import BotSignals
from app.shared.bot_protection.service import (
    CHECKOUT_PHONE_LIMIT,
    MIN_FORM_FILL_MS,
    BotSignalRejectedError,
    verify_bot_signals,
)

CHECKOUT_PATH = "/api/v1/storefront/orders"
STOREFRONT_PREFIX = "/api/v1/storefront"
HUMAN_BOT_SIGNALS = {"website": "", "form_elapsed_ms": 5000}


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
        "name": f"Guarded {unique}",
        "name_vi": f"Cây {unique}",
        "slug": f"guarded-{unique}",
        "price": Decimal("100000.00"),
        "price_vi": Decimal("100000.00"),
        "stock": 20,
        "sku": f"BOT-{unique}",
        "is_active": True,
    }
    values.update(overrides)
    plant = Plant(**values)
    session.add(plant)
    await session.commit()
    await session.refresh(plant)
    return plant


def _checkout_payload(plant: Plant, phone: str, **overrides: object) -> dict:
    payload: dict = {
        "customer": {"phone": phone, "name": "Nguyễn Văn A"},
        "shipping_address": "123 Nguyễn Huệ, Quận 1, TP.HCM",
        "items": [{"plant_id": str(plant.id), "quantity": 1}],
        **HUMAN_BOT_SIGNALS,
    }
    payload.update(overrides)
    return payload


async def _checkout(
    client: AsyncClient, plant: Plant, phone: str, **overrides: object
):
    return await client.post(
        CHECKOUT_PATH, json=_checkout_payload(plant, phone, **overrides)
    )


def _review_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Nguyen Van A",
        "rating": 5,
        "content": f"Cây đẹp {uuid4().hex}",
        **HUMAN_BOT_SIGNALS,
    }
    payload.update(overrides)
    return payload


async def _orders_for_phone(session: AsyncSession, phone: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Order)
        .join(Customer, Order.customer_id == Customer.id)
        .where(Customer.phone == phone)
    )
    return int(result.scalar_one())


async def _customer_exists(session: AsyncSession, phone: str) -> bool:
    result = await session.execute(select(Customer.id).where(Customer.phone == phone))
    return result.scalar_one_or_none() is not None


async def _reviews_with_content(session: AsyncSession, content: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(Review).where(Review.content == content)
    )
    return int(result.scalar_one())


async def _db_stock(session: AsyncSession, plant: Plant) -> int:
    result = await session.execute(select(Plant.stock).where(Plant.id == plant.id))
    return int(result.scalar_one())


# --------------------------------------------------------------------------
# verify_bot_signals
# --------------------------------------------------------------------------


def test_verify_bot_signals_accepts_a_human_submission() -> None:
    verify_bot_signals(BotSignals(website="", form_elapsed_ms=MIN_FORM_FILL_MS))
    verify_bot_signals(BotSignals(website=None, form_elapsed_ms=60_000))


@pytest.mark.parametrize(
    "signals",
    [
        pytest.param(BotSignals(website="https://spam.example", form_elapsed_ms=5000), id="honeypot"),
        pytest.param(BotSignals(website="", form_elapsed_ms=MIN_FORM_FILL_MS - 1), id="too-fast"),
        pytest.param(BotSignals(website="", form_elapsed_ms=None), id="missing-elapsed"),
        pytest.param(BotSignals(website="", form_elapsed_ms=-1), id="negative-elapsed"),
    ],
)
def test_verify_bot_signals_rejects_bots(signals: BotSignals) -> None:
    with pytest.raises(BotSignalRejectedError):
        verify_bot_signals(signals)


# --------------------------------------------------------------------------
# Checkout honeypot and minimum fill time
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signals",
    [
        pytest.param({"website": "https://spam.example", "form_elapsed_ms": 5000}, id="honeypot"),
        pytest.param({"website": "", "form_elapsed_ms": 1200}, id="too-fast"),
        pytest.param({"website": None, "form_elapsed_ms": None}, id="missing-signals"),
    ],
)
async def test_checkout_rejects_bot_signals_with_403(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    signals: dict,
) -> None:
    plant = await _seed_plant(test_db_session, test_category, stock=5)
    phone = _unique_phone()

    response = await _checkout(client, plant, phone, **signals)

    assert response.status_code == 403, response.text
    assert not await _customer_exists(test_db_session, phone)
    assert await _orders_for_phone(test_db_session, phone) == 0
    assert await _db_stock(test_db_session, plant) == 5


@pytest.mark.asyncio
async def test_checkout_without_signal_fields_is_rejected(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    phone = _unique_phone()
    payload = _checkout_payload(plant, phone)
    del payload["website"]
    del payload["form_elapsed_ms"]

    response = await client.post(CHECKOUT_PATH, json=payload)

    assert response.status_code == 403
    assert await _orders_for_phone(test_db_session, phone) == 0


# --------------------------------------------------------------------------
# Checkout phone rate limit
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_phone_limit_returns_429_with_retry_after(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category, stock=20)
    phone = _unique_phone()

    for _ in range(CHECKOUT_PHONE_LIMIT):
        response = await _checkout(client, plant, phone)
        assert response.status_code == 201, response.text

    blocked = await _checkout(client, plant, phone)

    assert blocked.status_code == 429, blocked.text
    retry_after = int(blocked.headers["retry-after"])
    assert 1 <= retry_after <= 3600
    assert await _orders_for_phone(test_db_session, phone) == CHECKOUT_PHONE_LIMIT
    assert await _db_stock(test_db_session, plant) == 20 - CHECKOUT_PHONE_LIMIT


@pytest.mark.asyncio
async def test_checkout_phone_limit_applies_to_the_normalized_phone(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    canonical = _unique_phone()
    formats = [f"+84{canonical[1:]}", f"84{canonical[1:]}", f"{canonical[:4]} {canonical[4:]}"]

    for phone in formats:
        response = await _checkout(client, plant, phone)
        assert response.status_code == 201, response.text

    blocked = await _checkout(client, plant, canonical)
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


@pytest.mark.asyncio
async def test_checkout_phone_limit_ignores_orders_older_than_an_hour(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    phone = _unique_phone()

    for _ in range(CHECKOUT_PHONE_LIMIT):
        response = await _checkout(client, plant, phone)
        assert response.status_code == 201, response.text

    customer_id = (
        await test_db_session.execute(select(Customer.id).where(Customer.phone == phone))
    ).scalar_one()
    await test_db_session.execute(
        update(Order)
        .where(Order.customer_id == customer_id)
        .values(created_at=func.now() - timedelta(hours=1, minutes=1))
    )
    await test_db_session.commit()

    response = await _checkout(client, plant, phone)
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_checkout_phone_limit_does_not_affect_other_phones(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    limited = _unique_phone()

    for _ in range(CHECKOUT_PHONE_LIMIT):
        assert (await _checkout(client, plant, limited)).status_code == 201
    assert (await _checkout(client, plant, limited)).status_code == 429

    other = await _checkout(client, plant, _unique_phone())
    assert other.status_code == 201, other.text


# --------------------------------------------------------------------------
# Public review protection
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signals",
    [
        pytest.param({"website": "https://spam.example"}, id="honeypot"),
        pytest.param({"form_elapsed_ms": 500}, id="too-fast"),
        pytest.param({"form_elapsed_ms": None}, id="missing-elapsed"),
    ],
)
async def test_shop_review_rejects_bot_signals_with_403(
    client: AsyncClient,
    test_db_session: AsyncSession,
    signals: dict,
) -> None:
    payload = _review_payload(**signals)

    response = await client.post(f"{STOREFRONT_PREFIX}/reviews", json=payload)

    assert response.status_code == 403, response.text
    assert await _reviews_with_content(test_db_session, payload["content"]) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signals",
    [
        pytest.param({"website": "https://spam.example"}, id="honeypot"),
        pytest.param({"form_elapsed_ms": 500}, id="too-fast"),
    ],
)
async def test_plant_review_rejects_bot_signals_with_403(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    signals: dict,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    payload = _review_payload(**signals)

    response = await client.post(
        f"{STOREFRONT_PREFIX}/plants/{plant.slug}/reviews", json=payload
    )

    assert response.status_code == 403, response.text
    assert await _reviews_with_content(test_db_session, payload["content"]) == 0


@pytest.mark.asyncio
async def test_reviews_are_not_rate_limited(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)

    for _ in range(CHECKOUT_PHONE_LIMIT + 2):
        shop = await client.post(f"{STOREFRONT_PREFIX}/reviews", json=_review_payload())
        assert shop.status_code == 201, shop.text
        plant_review = await client.post(
            f"{STOREFRONT_PREFIX}/plants/{plant.slug}/reviews",
            json=_review_payload(),
        )
        assert plant_review.status_code == 201, plant_review.text
