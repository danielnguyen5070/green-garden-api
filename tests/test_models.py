"""Database connection and schema relationship tests."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Category,
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    Plant,
    PlantImage,
    PlantImageType,
    PlantPotSize,
)


@pytest.mark.asyncio
async def test_database_connection(db_connection: None) -> None:
    """Database accepts connections (fixture runs SELECT 1)."""
    assert db_connection is None


@pytest.mark.asyncio
async def test_create_category(db_session: AsyncSession) -> None:
    category = Category(
        name="Indoor Plants",
        slug="indoor-plants-test",
        description="Plants for indoors",
    )
    db_session.add(category)
    await db_session.flush()

    assert category.id is not None
    assert category.is_active is True
    assert category.sort_order == 0


@pytest.mark.asyncio
async def test_plant_references_category(db_session: AsyncSession) -> None:
    category = Category(name="Outdoor", slug="outdoor-plants-test")
    db_session.add(category)
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Bird of Paradise",
        slug="bird-of-paradise-test",
        price=Decimal("145.00"),
        sku="SKU-BOP-TEST",
        stock=10,
    )
    db_session.add(plant)
    await db_session.flush()

    result = await db_session.execute(select(Plant).where(Plant.id == plant.id))
    loaded = result.scalar_one()
    assert loaded.category_id == category.id
    assert loaded.price == Decimal("145.00")


@pytest.mark.asyncio
async def test_plant_image_references_plant(db_session: AsyncSession) -> None:
    category = Category(name="Cats", slug="cats-img-test")
    db_session.add(category)
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Monstera",
        slug="monstera-img-test",
        price=Decimal("50.00"),
        sku="SKU-MON-IMG",
    )
    db_session.add(plant)
    await db_session.flush()

    image = PlantImage(
        plant_id=plant.id,
        url="https://cdn.example.com/monstera.jpg",
        type=PlantImageType.IMAGE,
        alt_text="Monstera leaf",
    )
    db_session.add(image)
    await db_session.flush()

    assert image.plant_id == plant.id
    assert image.sort_order == 0


@pytest.mark.asyncio
async def test_pot_size_references_plant(db_session: AsyncSession) -> None:
    category = Category(name="Pots", slug="pots-size-test")
    db_session.add(category)
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Fiddle Leaf",
        slug="fiddle-leaf-pot-test",
        price=Decimal("80.00"),
        sku="SKU-FLF-POT",
    )
    db_session.add(plant)
    await db_session.flush()

    pot = PlantPotSize(
        plant_id=plant.id,
        name="Large",
        price_adjustment=Decimal("20.00"),
        price_adjustment_vi=Decimal("100000.00"),
    )
    db_session.add(pot)
    await db_session.flush()

    assert pot.plant_id == plant.id
    assert pot.price_adjustment == Decimal("20.00")
    assert pot.price_adjustment_vi == Decimal("100000.00")


@pytest.mark.asyncio
async def test_customer_phone_unique(db_session: AsyncSession) -> None:
    first = Customer(phone="+84901111111", name="Alice")
    db_session.add(first)
    await db_session.flush()

    duplicate = Customer(phone="+84901111111", name="Bob")
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_order_references_customer(db_session: AsyncSession) -> None:
    customer = Customer(phone="+84902222222", name="Carol")
    db_session.add(customer)
    await db_session.flush()

    order = Order(
        customer_id=customer.id,
        order_number="GG-TEST-0001",
        status=OrderStatus.PENDING,
        total_amount=Decimal("100.00"),
        shipping_address="123 Nguyen Trai, Quan 1, Ho Chi Minh City",
    )
    db_session.add(order)
    await db_session.flush()

    assert order.customer_id == customer.id
    assert order.status == OrderStatus.PENDING


@pytest.mark.asyncio
async def test_order_item_references_order_and_plant(db_session: AsyncSession) -> None:
    category = Category(name="Order Cat", slug="order-item-cat")
    customer = Customer(phone="+84903333333", name="Dave")
    db_session.add_all([category, customer])
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Snake Plant",
        slug="snake-plant-order-test",
        price=Decimal("35.00"),
        sku="SKU-SNP-ORD",
    )
    db_session.add(plant)
    await db_session.flush()

    order = Order(
        customer_id=customer.id,
        order_number="GG-TEST-0002",
        status=OrderStatus.CONFIRMED,
        total_amount=Decimal("70.00"),
        shipping_address="456 Le Loi, Quan 3, Ho Chi Minh City",
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id,
        plant_id=plant.id,
        plant_name="Snake Plant",
        quantity=2,
        unit_price=Decimal("35.00"),
        pot_size="Medium",
    )
    db_session.add(item)
    await db_session.flush()

    assert item.order_id == order.id
    assert item.plant_id == plant.id
    assert item.plant_name == "Snake Plant"
    assert item.pot_size == "Medium"


@pytest.mark.asyncio
async def test_negative_plant_price_rejected(db_session: AsyncSession) -> None:
    category = Category(name="Neg Price", slug="neg-price-cat")
    db_session.add(category)
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Bad Price",
        slug="bad-price-plant",
        price=Decimal("-1.00"),
        sku="SKU-BAD-PRICE",
    )
    db_session.add(plant)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_negative_vietnamese_plant_price_rejected(db_session: AsyncSession) -> None:
    category = Category(name="Neg Price VI", slug="neg-price-vi-cat")
    db_session.add(category)
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Bad Vietnamese Price",
        slug="bad-price-vi-plant",
        price=Decimal("10.00"),
        price_vi=Decimal("-1.00"),
        sku="SKU-BAD-PRICE-VI",
    )
    db_session.add(plant)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_vietnamese_fields_default_to_null(db_session: AsyncSession) -> None:
    category = Category(name="Null VI", slug="null-vi-cat")
    db_session.add(category)
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="No Translation",
        slug="no-translation-plant",
        price=Decimal("10.00"),
        sku="SKU-NO-VI",
    )
    db_session.add(plant)
    await db_session.flush()

    assert category.name_vi is None
    assert category.description_vi is None
    assert plant.name_vi is None
    assert plant.description_vi is None
    assert plant.price_vi is None


@pytest.mark.asyncio
async def test_zero_quantity_rejected(db_session: AsyncSession) -> None:
    category = Category(name="Qty Cat", slug="qty-zero-cat")
    customer = Customer(phone="+84904444444", name="Eve")
    db_session.add_all([category, customer])
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Qty Plant",
        slug="qty-zero-plant",
        price=Decimal("10.00"),
        sku="SKU-QTY-ZERO",
    )
    db_session.add(plant)
    await db_session.flush()

    order = Order(
        customer_id=customer.id,
        order_number="GG-TEST-0003",
        status=OrderStatus.PENDING,
        total_amount=Decimal("0.00"),
        shipping_address="789 Address",
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id,
        plant_id=plant.id,
        plant_name="Qty Plant",
        quantity=0,
        unit_price=Decimal("10.00"),
    )
    db_session.add(item)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_negative_quantity_rejected(db_session: AsyncSession) -> None:
    category = Category(name="Qty Neg", slug="qty-neg-cat")
    customer = Customer(phone="+84905555555", name="Frank")
    db_session.add_all([category, customer])
    await db_session.flush()

    plant = Plant(
        category_id=category.id,
        name="Qty Neg Plant",
        slug="qty-neg-plant",
        price=Decimal("10.00"),
        sku="SKU-QTY-NEG",
    )
    db_session.add(plant)
    await db_session.flush()

    order = Order(
        customer_id=customer.id,
        order_number="GG-TEST-0004",
        status=OrderStatus.PENDING,
        total_amount=Decimal("0.00"),
        shipping_address="101 Address",
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id,
        plant_id=plant.id,
        plant_name="Qty Neg Plant",
        quantity=-1,
        unit_price=Decimal("10.00"),
    )
    db_session.add(item)

    with pytest.raises(IntegrityError):
        await db_session.flush()
