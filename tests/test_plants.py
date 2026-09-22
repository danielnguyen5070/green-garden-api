"""Plants / images / pot sizes API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.category import Category
from app.models.plant import (
    Plant,
    PlantDifficulty,
    PlantGrowthRate,
    PlantSpaceRequirement,
    PlantSunlight,
    PlantType,
    PlantWatering,
)
from app.models.plant_image import PlantImage, PlantImageType
from app.services.plant_service import get_plant, list_plants


AUTH_PREFIX = "/api/v1/auth"
PLANTS_PREFIX = "/api/v1/plants"
STOREFRONT_PREFIX = "/api/v1/storefront"


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _plant_payload(category: Category, **overrides: object) -> dict:
    unique = uuid4().hex[:8]
    payload = {
        "category_id": str(category.id),
        "name": f"Monstera {unique}",
        "slug": f"monstera-{unique}",
        "description": "Beautiful tropical plant.",
        "price": "250000.00",
        "stock": 20,
        "sku": f"MON-{unique}",
        "is_featured": True,
        "is_active": True,
    }
    payload.update(overrides)
    return payload


async def _create_plant(
    client: AsyncClient,
    category: Category,
    **overrides: object,
) -> dict:
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(category, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_plant(
    session: AsyncSession,
    category: Category,
    **overrides: object,
) -> Plant:
    unique = uuid4().hex[:8]
    values: dict = {
        "category_id": category.id,
        "name": f"Seeded {unique}",
        "slug": f"seeded-{unique}",
        "description": "Seeded plant.",
        "price": Decimal("100000.00"),
        "stock": 5,
        "sku": f"SEED-{unique}",
        "is_featured": False,
        "is_active": True,
    }
    values.update(overrides)
    plant = Plant(**values)
    session.add(plant)
    await session.commit()
    await session.refresh(plant)
    return plant


async def _seed_image(
    session: AsyncSession,
    plant: Plant,
    **overrides: object,
) -> PlantImage:
    values: dict = {
        "plant_id": plant.id,
        "url": f"https://cdn.example.com/{uuid4().hex[:8]}.jpg",
        "type": PlantImageType.IMAGE,
        "sort_order": 0,
    }
    values.update(overrides)
    image = PlantImage(**values)
    session.add(image)
    await session.commit()
    await session.refresh(image)
    return image


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_plants_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(PLANTS_PREFIX)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_plant_unauthenticated(
    client: AsyncClient,
    test_category: Category,
) -> None:
    response = await client.post(PLANTS_PREFIX, json=_plant_payload(test_category))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_plant_status_unauthenticated(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    response = await client.patch(
        f"{PLANTS_PREFIX}/{plant.id}/status",
        json={"is_active": False},
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_plant_success(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    payload = _plant_payload(test_category)
    response = await client.post(PLANTS_PREFIX, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == payload["name"]
    assert body["slug"] == payload["slug"]
    assert body["sku"] == str(payload["sku"]).upper()
    assert Decimal(body["price"]) == Decimal("250000.00")
    assert body["stock"] == 20
    assert body["is_featured"] is True
    assert body["is_active"] is True
    assert body["og_image_url"] is None
    assert body["category"]["id"] == str(test_category.id)
    assert body["images"] == []
    assert body["pot_sizes"] == []


@pytest.mark.asyncio
async def test_create_plant_with_og_image_url(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    url = "https://cdn.example.com/plants/monstera-og.jpg"
    body = await _create_plant(client, test_category, og_image_url=url)
    assert body["og_image_url"] == url


@pytest.mark.asyncio
async def test_create_plant_invalid_og_image_url(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, og_image_url="not-a-url"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_plant_og_image_url_and_clear(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(
        client,
        test_category,
        og_image_url="https://cdn.example.com/plants/old-og.jpg",
    )
    assert created["og_image_url"] == "https://cdn.example.com/plants/old-og.jpg"

    updated = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"og_image_url": "https://cdn.example.com/plants/new-og.jpg"},
    )
    assert updated.status_code == 200
    assert updated.json()["og_image_url"] == "https://cdn.example.com/plants/new-og.jpg"

    cleared = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"og_image_url": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["og_image_url"] is None

    # Omitting the field leaves the previous value
    restored = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"og_image_url": "https://cdn.example.com/plants/kept-og.jpg"},
    )
    assert restored.status_code == 200
    omitted = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"name": created["name"]},
    )
    assert omitted.status_code == 200
    assert omitted.json()["og_image_url"] == "https://cdn.example.com/plants/kept-og.jpg"


@pytest.mark.asyncio
async def test_create_plant_normalizes_slug_and_sku(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    unique = uuid4().hex[:8]
    body = await _create_plant(
        client,
        test_category,
        name=f"  Spaced Name {unique}  ",
        slug=f"  Monstera Deliciosa {unique}  ",
        sku=f"  mon-{unique}  ",
    )
    assert body["name"] == f"Spaced Name {unique}"
    assert body["slug"] == f"monstera-deliciosa-{unique}"
    assert body["sku"] == f"MON-{unique}".upper()


@pytest.mark.asyncio
async def test_create_plant_invalid_category(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    payload = _plant_payload(test_category, category_id=str(uuid4()))
    response = await client.post(PLANTS_PREFIX, json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


@pytest.mark.asyncio
async def test_create_plant_duplicate_slug(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    existing = await _create_plant(client, test_category)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, slug=existing["slug"]),
    )
    assert response.status_code == 409
    assert "slug" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_plant_duplicate_sku(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    existing = await _create_plant(client, test_category)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, sku=existing["sku"]),
    )
    assert response.status_code == 409
    assert "SKU" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_plant_negative_price(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, price="-1.00"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_plant_negative_stock(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, stock=-5),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# List
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_plants_pagination(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    for _ in range(3):
        await _seed_plant(test_db_session, test_category)

    response = await client.get(
        PLANTS_PREFIX,
        params={"category_id": str(test_category.id), "page": 1, "page_size": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2

    page_two = await client.get(
        PLANTS_PREFIX,
        params={"category_id": str(test_category.id), "page": 2, "page_size": 2},
    )
    assert len(page_two.json()["items"]) == 1


@pytest.mark.asyncio
async def test_list_plants_invalid_page_size(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(PLANTS_PREFIX, params={"page_size": 1000})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_plants_search_by_name_and_sku(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    unique = uuid4().hex[:8]
    target = await _seed_plant(
        test_db_session,
        test_category,
        name=f"Findable Ficus {unique}",
        slug=f"findable-ficus-{unique}",
        sku=f"FIND-{unique}".upper(),
    )
    await _seed_plant(test_db_session, test_category)

    by_name = await client.get(PLANTS_PREFIX, params={"search": f"Findable Ficus {unique}"})
    assert [item["id"] for item in by_name.json()["items"]] == [str(target.id)]

    by_sku = await client.get(PLANTS_PREFIX, params={"search": f"FIND-{unique}"})
    assert [item["id"] for item in by_sku.json()["items"]] == [str(target.id)]


@pytest.mark.asyncio
async def test_list_plants_category_filter(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    other_category = Category(
        name=f"Other {uuid4().hex[:8]}",
        slug=f"other-{uuid4().hex[:8]}",
        is_active=True,
    )
    test_db_session.add(other_category)
    await test_db_session.commit()
    await test_db_session.refresh(other_category)

    mine = await _seed_plant(test_db_session, test_category)
    await _seed_plant(test_db_session, other_category)

    response = await client.get(
        PLANTS_PREFIX,
        params={"category_id": str(test_category.id)},
    )
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(mine.id)]


@pytest.mark.asyncio
async def test_list_plants_active_and_featured_filters(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    active_featured = await _seed_plant(
        test_db_session, test_category, is_active=True, is_featured=True
    )
    inactive = await _seed_plant(
        test_db_session, test_category, is_active=False, is_featured=False
    )

    active_only = await client.get(
        PLANTS_PREFIX,
        params={"category_id": str(test_category.id), "is_active": "true"},
    )
    assert [item["id"] for item in active_only.json()["items"]] == [str(active_featured.id)]

    inactive_only = await client.get(
        PLANTS_PREFIX,
        params={"category_id": str(test_category.id), "is_active": "false"},
    )
    assert [item["id"] for item in inactive_only.json()["items"]] == [str(inactive.id)]

    featured_only = await client.get(
        PLANTS_PREFIX,
        params={"category_id": str(test_category.id), "is_featured": "true"},
    )
    assert [item["id"] for item in featured_only.json()["items"]] == [str(active_featured.id)]


@pytest.mark.asyncio
async def test_list_plants_price_range_filter(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    cheap = await _seed_plant(test_db_session, test_category, price=Decimal("50.00"))
    await _seed_plant(test_db_session, test_category, price=Decimal("5000.00"))

    response = await client.get(
        PLANTS_PREFIX,
        params={
            "category_id": str(test_category.id),
            "min_price": "0",
            "max_price": "100",
        },
    )
    assert [item["id"] for item in response.json()["items"]] == [str(cheap.id)]


@pytest.mark.asyncio
async def test_list_plants_sorting(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    cheap = await _seed_plant(test_db_session, test_category, price=Decimal("10.00"))
    expensive = await _seed_plant(test_db_session, test_category, price=Decimal("999.00"))

    ascending = await client.get(
        PLANTS_PREFIX,
        params={
            "category_id": str(test_category.id),
            "sort": "price",
            "order": "asc",
        },
    )
    assert [item["id"] for item in ascending.json()["items"]] == [
        str(cheap.id),
        str(expensive.id),
    ]

    descending = await client.get(
        PLANTS_PREFIX,
        params={
            "category_id": str(test_category.id),
            "sort": "price",
            "order": "desc",
        },
    )
    assert [item["id"] for item in descending.json()["items"]] == [
        str(expensive.id),
        str(cheap.id),
    ]


@pytest.mark.asyncio
async def test_list_plants_invalid_sort_field(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(PLANTS_PREFIX, params={"sort": "not_a_column"})
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Get detail
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_plant_detail(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(client, test_category)

    response = await client.get(f"{PLANTS_PREFIX}/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["category"]["slug"] == test_category.slug
    assert body["images"] == []
    assert body["pot_sizes"] == []


@pytest.mark.asyncio
async def test_get_plant_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{PLANTS_PREFIX}/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Plant not found"


# --------------------------------------------------------------------------
# Update
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_plant_success(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(client, test_category)

    response = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"name": "Renamed Plant", "price": "12345.67", "stock": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Plant"
    assert Decimal(body["price"]) == Decimal("12345.67")
    assert body["stock"] == 3
    assert body["slug"] == created["slug"]


@pytest.mark.asyncio
async def test_update_plant_duplicate_slug(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    first = await _create_plant(client, test_category)
    second = await _create_plant(client, test_category)

    response = await client.patch(
        f"{PLANTS_PREFIX}/{second['id']}",
        json={"slug": first["slug"]},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_plant_duplicate_sku(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    first = await _create_plant(client, test_category)
    second = await _create_plant(client, test_category)

    response = await client.patch(
        f"{PLANTS_PREFIX}/{second['id']}",
        json={"sku": first["sku"]},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_plant_invalid_category(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(client, test_category)

    response = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"category_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


@pytest.mark.asyncio
async def test_update_plant_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(f"{PLANTS_PREFIX}/{uuid4()}", json={"name": "Nope"})
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_and_activate_plant(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(client, test_category)

    deactivated = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}/status",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    activated = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}/status",
        json={"is_active": True},
    )
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True


@pytest.mark.asyncio
async def test_plant_status_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(
        f"{PLANTS_PREFIX}/{uuid4()}/status",
        json={"is_active": False},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plant_image_crud(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    plant = await _create_plant(client, test_category)

    created = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/images",
        json={
            "url": "https://cdn.example.com/monstera.jpg",
            "type": "image",
            "alt_text": "Monstera Deliciosa",
            "sort_order": 0,
        },
    )
    assert created.status_code == 201
    image = created.json()
    assert image["plant_id"] == plant["id"]
    assert image["type"] == "image"
    assert image["alt_text"] == "Monstera Deliciosa"

    listed = await client.get(f"{PLANTS_PREFIX}/{plant['id']}/images")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [image["id"]]

    updated = await client.patch(
        f"{PLANTS_PREFIX}/{plant['id']}/images/{image['id']}",
        json={"alt_text": "Updated alt", "sort_order": 5, "type": "video"},
    )
    assert updated.status_code == 200
    assert updated.json()["alt_text"] == "Updated alt"
    assert updated.json()["sort_order"] == 5
    assert updated.json()["type"] == "video"

    deleted = await client.delete(
        f"{PLANTS_PREFIX}/{plant['id']}/images/{image['id']}"
    )
    assert deleted.status_code == 204

    empty = await client.get(f"{PLANTS_PREFIX}/{plant['id']}/images")
    assert empty.json() == []


@pytest.mark.asyncio
async def test_plant_image_invalid_url(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    plant = await _create_plant(client, test_category)
    response = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/images",
        json={"url": "not-a-url", "type": "image"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_plant_image_invalid_type(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    plant = await _create_plant(client, test_category)
    response = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/images",
        json={"url": "https://cdn.example.com/a.jpg", "type": "audio"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_plant_image_must_belong_to_plant(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    owner = await _create_plant(client, test_category)
    other = await _create_plant(client, test_category)

    created = await client.post(
        f"{PLANTS_PREFIX}/{owner['id']}/images",
        json={"url": "https://cdn.example.com/owned.jpg", "type": "image"},
    )
    image_id = created.json()["id"]

    patched = await client.patch(
        f"{PLANTS_PREFIX}/{other['id']}/images/{image_id}",
        json={"sort_order": 2},
    )
    assert patched.status_code == 404

    deleted = await client.delete(f"{PLANTS_PREFIX}/{other['id']}/images/{image_id}")
    assert deleted.status_code == 404


@pytest.mark.asyncio
async def test_plant_images_missing_plant(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    missing = uuid4()

    listed = await client.get(f"{PLANTS_PREFIX}/{missing}/images")
    assert listed.status_code == 404

    created = await client.post(
        f"{PLANTS_PREFIX}/{missing}/images",
        json={"url": "https://cdn.example.com/a.jpg", "type": "image"},
    )
    assert created.status_code == 404


# --------------------------------------------------------------------------
# Pot sizes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plant_pot_size_crud(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    plant = await _create_plant(client, test_category)

    created = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes",
        json={
            "name": "Size M",
            "price_adjustment": "50000.00",
            "sort_order": 1,
            "is_active": True,
        },
    )
    assert created.status_code == 201
    pot_size = created.json()
    assert pot_size["plant_id"] == plant["id"]
    assert pot_size["name"] == "Size M"
    assert Decimal(pot_size["price_adjustment"]) == Decimal("50000.00")

    listed = await client.get(f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes")
    assert [item["id"] for item in listed.json()] == [pot_size["id"]]

    updated = await client.patch(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes/{pot_size['id']}",
        json={"name": "Size L", "price_adjustment": "0.00", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Size L"
    assert Decimal(updated.json()["price_adjustment"]) == Decimal("0.00")
    assert updated.json()["is_active"] is False

    deleted = await client.delete(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes/{pot_size['id']}"
    )
    assert deleted.status_code == 204
    assert (await client.get(f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes")).json() == []


@pytest.mark.asyncio
async def test_plant_pot_size_requires_name(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    plant = await _create_plant(client, test_category)
    response = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes",
        json={"name": "   ", "price_adjustment": "1000.00"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_plant_pot_size_must_belong_to_plant(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    owner = await _create_plant(client, test_category)
    other = await _create_plant(client, test_category)

    created = await client.post(
        f"{PLANTS_PREFIX}/{owner['id']}/pot-sizes",
        json={"name": "Size S", "price_adjustment": "0.00"},
    )
    size_id = created.json()["id"]

    patched = await client.patch(
        f"{PLANTS_PREFIX}/{other['id']}/pot-sizes/{size_id}",
        json={"name": "Hijack"},
    )
    assert patched.status_code == 404

    deleted = await client.delete(f"{PLANTS_PREFIX}/{other['id']}/pot-sizes/{size_id}")
    assert deleted.status_code == 404


@pytest.mark.asyncio
async def test_plant_pot_sizes_missing_plant(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    missing = uuid4()

    listed = await client.get(f"{PLANTS_PREFIX}/{missing}/pot-sizes")
    assert listed.status_code == 404

    created = await client.post(
        f"{PLANTS_PREFIX}/{missing}/pot-sizes",
        json={"name": "Size M", "price_adjustment": "0.00"},
    )
    assert created.status_code == 404


# --------------------------------------------------------------------------
# Vietnamese fields
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_plant_with_vietnamese_fields(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    body = await _create_plant(
        client,
        test_category,
        name="Monstera Deliciosa",
        description="A beautiful tropical indoor plant.",
        name_vi="Cây Trầu Bà Nam Mỹ",
        description_vi="Một loại cây nhiệt đới đẹp, phù hợp trồng trong nhà.",
        price="25.00",
        price_vi="650000.00",
    )

    assert body["name"] == "Monstera Deliciosa"
    assert body["name_vi"] == "Cây Trầu Bà Nam Mỹ"
    assert body["description"] == "A beautiful tropical indoor plant."
    assert body["description_vi"] == (
        "Một loại cây nhiệt đới đẹp, phù hợp trồng trong nhà."
    )
    assert Decimal(body["price"]) == Decimal("25.00")
    assert Decimal(body["price_vi"]) == Decimal("650000.00")
    assert "slug_vi" not in body


@pytest.mark.asyncio
async def test_create_plant_without_vietnamese_fields(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    body = await _create_plant(client, test_category)

    assert body["name_vi"] is None
    assert body["description_vi"] is None
    assert body["price_vi"] is None
    assert body["long_description"] is None
    assert body["long_description_vi"] is None
    assert body["plant_type"] is None
    assert body["difficulty"] is None
    assert body["growth_rate"] is None
    assert body["sunlight"] is None
    assert body["watering"] is None
    assert body["space_requirement"] is None
    assert body["indoor_suitable"] is None
    assert body["outdoor_suitable"] is None
    assert body["pet_safe"] is None
    assert body["beginner_friendly"] is None


@pytest.mark.asyncio
async def test_create_plant_with_care_attributes(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    body = await _create_plant(
        client,
        test_category,
        plant_type="foliage",
        difficulty="easy",
        growth_rate="fast",
        sunlight="partial_shade",
        watering="moderate",
        space_requirement="medium",
        indoor_suitable=True,
        outdoor_suitable=False,
        pet_safe=True,
        beginner_friendly=True,
    )
    assert body["plant_type"] == "foliage"
    assert body["difficulty"] == "easy"
    assert body["growth_rate"] == "fast"
    assert body["sunlight"] == "partial_shade"
    assert body["watering"] == "moderate"
    assert body["space_requirement"] == "medium"
    assert body["indoor_suitable"] is True
    assert body["outdoor_suitable"] is False
    assert body["pet_safe"] is True
    assert body["beginner_friendly"] is True


@pytest.mark.asyncio
async def test_create_plant_invalid_care_enum(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, difficulty="impossible"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_plant_care_attributes_and_clear(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(
        client,
        test_category,
        plant_type="succulent",
        difficulty="easy",
        growth_rate="slow",
        sunlight="full_sun",
        watering="low",
        space_requirement="small",
        indoor_suitable=True,
        outdoor_suitable=True,
        pet_safe=False,
        beginner_friendly=True,
    )

    updated = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={
            "plant_type": "cactus",
            "difficulty": "moderate",
            "growth_rate": "moderate",
            "sunlight": "low_light",
            "watering": "high",
            "space_requirement": "large",
            "indoor_suitable": False,
            "outdoor_suitable": True,
            "pet_safe": True,
            "beginner_friendly": False,
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["plant_type"] == "cactus"
    assert body["difficulty"] == "moderate"
    assert body["growth_rate"] == "moderate"
    assert body["sunlight"] == "low_light"
    assert body["watering"] == "high"
    assert body["space_requirement"] == "large"
    assert body["indoor_suitable"] is False
    assert body["outdoor_suitable"] is True
    assert body["pet_safe"] is True
    assert body["beginner_friendly"] is False

    cleared = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={
            "plant_type": None,
            "difficulty": None,
            "growth_rate": None,
            "sunlight": None,
            "watering": None,
            "space_requirement": None,
            "indoor_suitable": None,
            "outdoor_suitable": None,
            "pet_safe": None,
            "beginner_friendly": None,
        },
    )
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["plant_type"] is None
    assert cleared_body["difficulty"] is None
    assert cleared_body["growth_rate"] is None
    assert cleared_body["sunlight"] is None
    assert cleared_body["watering"] is None
    assert cleared_body["space_requirement"] is None
    assert cleared_body["indoor_suitable"] is None
    assert cleared_body["outdoor_suitable"] is None
    assert cleared_body["pet_safe"] is None
    assert cleared_body["beginner_friendly"] is None

    # Omitting fields leaves previous values
    kept = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"name": "Care Attributes Kept"},
    )
    assert kept.status_code == 200
    assert kept.json()["plant_type"] is None
    assert kept.json()["beginner_friendly"] is None


@pytest.mark.asyncio
async def test_get_plant_returns_care_attributes(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(
        client,
        test_category,
        plant_type="herb",
        difficulty="hard",
        growth_rate="fast",
        sunlight="partial_sun",
        watering="high",
        space_requirement="medium",
        indoor_suitable=False,
        outdoor_suitable=True,
        pet_safe=False,
        beginner_friendly=False,
    )

    response = await client.get(f"{PLANTS_PREFIX}/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["plant_type"] == "herb"
    assert body["difficulty"] == "hard"
    assert body["growth_rate"] == "fast"
    assert body["sunlight"] == "partial_sun"
    assert body["watering"] == "high"
    assert body["space_requirement"] == "medium"
    assert body["indoor_suitable"] is False
    assert body["outdoor_suitable"] is True
    assert body["pet_safe"] is False
    assert body["beginner_friendly"] is False


@pytest.mark.asyncio
async def test_public_plant_detail_returns_care_attributes(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(
        test_db_session,
        test_category,
        plant_type=PlantType.FERN,
        difficulty=PlantDifficulty.EASY,
        growth_rate=PlantGrowthRate.SLOW,
        sunlight=PlantSunlight.SHADE,
        watering=PlantWatering.MODERATE,
        space_requirement=PlantSpaceRequirement.SMALL,
        indoor_suitable=True,
        outdoor_suitable=False,
        pet_safe=True,
        beginner_friendly=True,
    )

    response = await client.get(f"{STOREFRONT_PREFIX}/plants/{plant.slug}")
    assert response.status_code == 200
    body = response.json()
    assert body["plant_type"] == "fern"
    assert body["difficulty"] == "easy"
    assert body["growth_rate"] == "slow"
    assert body["sunlight"] == "shade"
    assert body["watering"] == "moderate"
    assert body["space_requirement"] == "small"
    assert body["indoor_suitable"] is True
    assert body["outdoor_suitable"] is False
    assert body["pet_safe"] is True
    assert body["beginner_friendly"] is True


@pytest.mark.asyncio
async def test_create_plant_with_long_descriptions(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    long_en = ("Monstera care guide. " * 200).strip()
    long_vi = ("Hướng dẫn chăm sóc trầu bà. " * 200).strip()
    assert len(long_en) > 2000
    assert len(long_vi) > 2000

    body = await _create_plant(
        client,
        test_category,
        long_description=f"  {long_en}  ",
        long_description_vi=f"  {long_vi}  ",
    )
    assert body["long_description"] == long_en
    assert body["long_description_vi"] == long_vi


@pytest.mark.asyncio
async def test_update_plant_long_descriptions_and_clear(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(
        client,
        test_category,
        long_description="Initial long English SEO copy.",
        long_description_vi="Mô tả SEO tiếng Việt dài.",
    )

    updated = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={
            "long_description": "Updated long English SEO copy.",
            "long_description_vi": "Mô tả SEO tiếng Việt đã cập nhật.",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["long_description"] == "Updated long English SEO copy."
    assert updated.json()["long_description_vi"] == "Mô tả SEO tiếng Việt đã cập nhật."
    assert updated.json()["description"] == created["description"]

    cleared = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"long_description": None, "long_description_vi": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["long_description"] is None
    assert cleared.json()["long_description_vi"] is None


@pytest.mark.asyncio
async def test_public_plant_detail_returns_long_descriptions(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        long_description="Long English SEO content for the product page.",
        long_description_vi="Nội dung SEO tiếng Việt dài cho trang sản phẩm.",
    )

    response = await client.get(f"{STOREFRONT_PREFIX}/plants/{plant.slug}")
    assert response.status_code == 200
    body = response.json()
    assert body["long_description"] == (
        "Long English SEO content for the product page."
    )
    assert body["long_description_vi"] == (
        "Nội dung SEO tiếng Việt dài cho trang sản phẩm."
    )


@pytest.mark.asyncio
async def test_create_plant_negative_vietnamese_price(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, price_vi="-1.00"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_plant_vietnamese_fields(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(client, test_category, price="25.00")

    response = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={
            "name_vi": "Cây Trầu Bà Nam Mỹ",
            "description_vi": "Một loại cây nhiệt đới đẹp.",
            "price_vi": "650000.00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name_vi"] == "Cây Trầu Bà Nam Mỹ"
    assert body["description_vi"] == "Một loại cây nhiệt đới đẹp."
    assert Decimal(body["price_vi"]) == Decimal("650000.00")
    # English values stay untouched when only Vietnamese fields are sent
    assert body["name"] == created["name"]
    assert body["description"] == created["description"]
    assert Decimal(body["price"]) == Decimal("25.00")


@pytest.mark.asyncio
async def test_update_plant_clears_vietnamese_fields(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(
        client,
        test_category,
        name_vi="Cây Trầu Bà Nam Mỹ",
        description_vi="Một loại cây nhiệt đới đẹp.",
        price_vi="650000.00",
    )

    response = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"name_vi": None, "description_vi": None, "price_vi": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name_vi"] is None
    assert body["description_vi"] is None
    assert body["price_vi"] is None


@pytest.mark.asyncio
async def test_update_plant_negative_vietnamese_price(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(client, test_category)

    response = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}",
        json={"price_vi": "-1.00"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_plant_returns_vietnamese_fields(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(
        client,
        test_category,
        name_vi="Cây Trầu Bà Nam Mỹ",
        description_vi="Một loại cây nhiệt đới đẹp.",
        price_vi="650000.00",
    )

    detail = await client.get(f"{PLANTS_PREFIX}/{created['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["name_vi"] == "Cây Trầu Bà Nam Mỹ"
    assert body["description_vi"] == "Một loại cây nhiệt đới đẹp."
    assert Decimal(body["price_vi"]) == Decimal("650000.00")

    listed = await client.get(
        PLANTS_PREFIX,
        params={"search": created["sku"]},
    )
    rows = listed.json()["items"]
    assert [row["name_vi"] for row in rows] == ["Cây Trầu Bà Nam Mỹ"]
    assert [Decimal(row["price_vi"]) for row in rows] == [Decimal("650000.00")]


@pytest.mark.asyncio
async def test_plant_status_keeps_vietnamese_fields(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    created = await _create_plant(
        client,
        test_category,
        name_vi="Cây Trầu Bà Nam Mỹ",
        price_vi="650000.00",
    )

    response = await client.patch(
        f"{PLANTS_PREFIX}/{created['id']}/status",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["name_vi"] == "Cây Trầu Bà Nam Mỹ"
    assert Decimal(response.json()["price_vi"]) == Decimal("650000.00")


@pytest.mark.asyncio
async def test_pot_size_vietnamese_price_adjustment(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    """Both locales keep their own adjustment: 25+5 AUD and 650k+100k VND."""
    await _login(client, active_admin)
    plant = await _create_plant(
        client,
        test_category,
        price="25.00",
        price_vi="650000.00",
    )

    created = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes",
        json={
            "name": "Large",
            "price_adjustment": "5.00",
            "price_adjustment_vi": "100000.00",
        },
    )
    assert created.status_code == 201
    pot_size = created.json()
    assert Decimal(pot_size["price_adjustment"]) == Decimal("5.00")
    assert Decimal(pot_size["price_adjustment_vi"]) == Decimal("100000.00")

    assert Decimal(plant["price"]) + Decimal(pot_size["price_adjustment"]) == Decimal(
        "30.00"
    )
    assert Decimal(plant["price_vi"]) + Decimal(
        pot_size["price_adjustment_vi"]
    ) == Decimal("750000.00")

    listed = await client.get(f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes")
    rows = listed.json()
    assert [Decimal(row["price_adjustment"]) for row in rows] == [Decimal("5.00")]
    assert [Decimal(row["price_adjustment_vi"]) for row in rows] == [
        Decimal("100000.00")
    ]

    updated = await client.patch(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes/{pot_size['id']}",
        json={"price_adjustment_vi": "120000.00"},
    )
    assert updated.status_code == 200
    # The default-locale adjustment is unaffected by the Vietnamese update
    assert Decimal(updated.json()["price_adjustment"]) == Decimal("5.00")
    assert Decimal(updated.json()["price_adjustment_vi"]) == Decimal("120000.00")

    cleared = await client.patch(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes/{pot_size['id']}",
        json={"price_adjustment_vi": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["price_adjustment_vi"] is None


@pytest.mark.asyncio
async def test_pot_size_without_vietnamese_price_adjustment(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    plant = await _create_plant(client, test_category)

    created = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes",
        json={"name": "Small", "price_adjustment": "5.00"},
    )
    assert created.status_code == 201
    assert created.json()["price_adjustment_vi"] is None


@pytest.mark.asyncio
async def test_pot_size_negative_vietnamese_price_adjustment(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
) -> None:
    await _login(client, active_admin)
    plant = await _create_plant(client, test_category)

    response = await client.post(
        f"{PLANTS_PREFIX}/{plant['id']}/pot-sizes",
        json={
            "name": "Large",
            "price_adjustment": "5.00",
            "price_adjustment_vi": "-1.00",
        },
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Public storefront
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_plant_detail_is_accessible_without_auth(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category, is_active=True, stock=7)

    response = await client.get(f"{STOREFRONT_PREFIX}/plants/{plant.slug}")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == plant.slug
    assert body["in_stock"] is True
    assert body["og_image_url"] is None
    assert body["category"]["id"] == str(test_category.id)
    assert "sku" not in body
    assert "is_active" not in body


@pytest.mark.asyncio
async def test_public_plants_return_og_image_url(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    url = "https://cdn.example.com/plants/og-preview.jpg"
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        og_image_url=url,
    )

    detail = await client.get(f"{STOREFRONT_PREFIX}/plants/{plant.slug}")
    assert detail.status_code == 200
    assert detail.json()["og_image_url"] == url

    listed = await client.get(
        f"{STOREFRONT_PREFIX}/plants",
        params={"category_id": str(test_category.id)},
    )
    assert listed.status_code == 200
    row = next(item for item in listed.json()["items"] if item["id"] == str(plant.id))
    assert row["og_image_url"] == url


@pytest.mark.asyncio
async def test_public_endpoints_hide_inactive_plants(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    inactive = await _seed_plant(test_db_session, test_category, is_active=False)
    active = await _seed_plant(test_db_session, test_category, is_active=True)

    detail = await client.get(f"{STOREFRONT_PREFIX}/plants/{inactive.slug}")
    assert detail.status_code == 404

    listed = await client.get(
        f"{STOREFRONT_PREFIX}/plants",
        params={"category_id": str(test_category.id)},
    )
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()["items"]]
    assert str(active.id) in ids
    assert str(inactive.id) not in ids


@pytest.mark.asyncio
async def test_public_plant_detail_not_found(client: AsyncClient) -> None:
    response = await client.get(f"{STOREFRONT_PREFIX}/plants/missing-plant-slug")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_list_hides_admin_fields(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _seed_plant(test_db_session, test_category, is_active=True)
    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants",
        params={"category_id": str(test_category.id)},
    )
    for item in response.json()["items"]:
        assert "sku" not in item
        assert "is_active" not in item
        assert "created_at" not in item
        assert "updated_at" not in item


@pytest.mark.asyncio
async def test_public_plants_return_vietnamese_fields(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name_vi="Cây Trầu Bà Nam Mỹ",
        description_vi="Một loại cây nhiệt đới đẹp.",
        price_vi=Decimal("650000.00"),
    )

    detail = await client.get(f"{STOREFRONT_PREFIX}/plants/{plant.slug}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["name_vi"] == "Cây Trầu Bà Nam Mỹ"
    assert body["description_vi"] == "Một loại cây nhiệt đới đẹp."
    assert Decimal(body["price_vi"]) == Decimal("650000.00")

    listed = await client.get(
        f"{STOREFRONT_PREFIX}/plants",
        params={"search": plant.sku},
    )
    rows = listed.json()["items"]
    assert [row["name_vi"] for row in rows] == ["Cây Trầu Bà Nam Mỹ"]
    assert [Decimal(row["price_vi"]) for row in rows] == [Decimal("650000.00")]


@pytest.mark.asyncio
async def test_public_list_returns_card_fields(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """The listing carries the copy the homepage renders, without a detail call."""
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        stock=7,
        is_featured=True,
        name_vi="Cây Trầu Bà Nam Mỹ",
        description="A beautiful tropical indoor plant.",
        description_vi="Một loại cây nhiệt đới đẹp.",
        price=Decimal("250000.00"),
        price_vi=Decimal("650000.00"),
    )
    await _seed_image(test_db_session, plant, url="https://cdn.example.com/a.jpg")

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants",
        params={"search": plant.sku},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]

    assert item["id"] == str(plant.id)
    assert item["name"] == plant.name
    assert item["name_vi"] == "Cây Trầu Bà Nam Mỹ"
    assert item["slug"] == plant.slug
    assert item["description"] == "A beautiful tropical indoor plant."
    assert item["description_vi"] == "Một loại cây nhiệt đới đẹp."
    assert Decimal(item["price"]) == Decimal("250000.00")
    assert Decimal(item["price_vi"]) == Decimal("650000.00")
    assert item["stock"] == 7
    assert item["is_featured"] is True
    assert item["category"]["id"] == str(test_category.id)
    assert len(item["images"]) == 1


@pytest.mark.asyncio
async def test_public_list_orders_images_by_sort_order(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category, is_active=True)
    # Inserted out of order on purpose.
    await _seed_image(
        test_db_session,
        plant,
        url="https://cdn.example.com/third.jpg",
        sort_order=2,
    )
    await _seed_image(
        test_db_session,
        plant,
        url="https://cdn.example.com/first.jpg",
        alt_text="Front view",
        sort_order=0,
    )
    await _seed_image(
        test_db_session,
        plant,
        url="https://cdn.example.com/second.jpg",
        sort_order=1,
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants",
        params={"search": plant.sku},
    )
    images = response.json()["items"][0]["images"]

    assert [image["sort_order"] for image in images] == [0, 1, 2]
    assert [image["url"] for image in images] == [
        "https://cdn.example.com/first.jpg",
        "https://cdn.example.com/second.jpg",
        "https://cdn.example.com/third.jpg",
    ]
    assert images[0]["alt_text"] == "Front view"
    assert images[1]["alt_text"] is None
    assert set(images[0]) == {"id", "url", "type", "alt_text", "sort_order"}


@pytest.mark.asyncio
async def test_public_list_images_belong_to_their_own_plant(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    with_media = await _seed_plant(test_db_session, test_category, is_active=True)
    without_media = await _seed_plant(test_db_session, test_category, is_active=True)
    await _seed_image(
        test_db_session,
        with_media,
        url="https://cdn.example.com/only.jpg",
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants",
        params={"category_id": str(test_category.id), "page_size": 100},
    )
    images_by_plant = {
        item["id"]: item["images"] for item in response.json()["items"]
    }

    assert [image["url"] for image in images_by_plant[str(with_media.id)]] == [
        "https://cdn.example.com/only.jpg"
    ]
    # A plant without media returns an empty list, never `null`.
    assert images_by_plant[str(without_media.id)] == []


@pytest.mark.asyncio
async def test_public_list_image_queries_do_not_grow_with_row_count(
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """Storefront media is one extra query per page, not one per plant."""
    for _ in range(5):
        plant = await _seed_plant(test_db_session, test_category, is_active=True)
        for sort_order in range(3):
            await _seed_image(
                test_db_session,
                plant,
                url=f"https://cdn.example.com/{uuid4().hex[:8]}.jpg",
                sort_order=sort_order,
            )

    test_db_session.expunge_all()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        items, _ = await list_plants(
            test_db_session,
            page=1,
            page_size=5,
            category_id=test_category.id,
            is_active=True,
            with_images=True,
        )
        # Touch the collections the storefront serializes: already loaded, so
        # a lazy load here would show up as an extra statement.
        loaded = [len(plant.images) for plant in items]
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

    assert len(items) == 5
    assert loaded == [3, 3, 3, 3, 3]
    # count + rows + categories + images
    assert len(statements) == 4


@pytest.mark.asyncio
async def test_queries_do_not_grow_with_row_count(
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """Listing and detail use a fixed number of queries regardless of row count."""
    plants = []
    for _ in range(5):
        plant = await _seed_plant(test_db_session, test_category)
        test_db_session.add(
            PlantImage(
                plant_id=plant.id,
                url="https://cdn.example.com/a.jpg",
                type=PlantImageType.IMAGE,
            )
        )
        await test_db_session.commit()
        plants.append(plant)

    # Drop the seeded instances so the reads below behave like a fresh request.
    test_db_session.expunge_all()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        statements.clear()
        items, _ = await list_plants(
            test_db_session,
            page=1,
            page_size=5,
            category_id=test_category.id,
        )
        list_queries = len(statements)

        # The listing intentionally skips collections, so start detail from a
        # clean identity map like a separate request would.
        test_db_session.expunge_all()

        statements.clear()
        detail = await get_plant(test_db_session, plants[0].id)
        detail_queries = len(statements)
    finally:
        event.remove(Engine, "before_cursor_execute", _record)

    assert len(items) == 5
    # count + rows + category
    assert list_queries <= 3
    # plant + category + images + pot sizes
    assert detail_queries <= 4
    assert detail.category is not None
    assert len(detail.images) == 1


@pytest.mark.asyncio
async def test_public_detail_only_returns_active_pot_sizes(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category, is_active=True)

    await _login(client, active_admin)
    visible = await client.post(
        f"{PLANTS_PREFIX}/{plant.id}/pot-sizes",
        json={"name": "Visible", "price_adjustment": "0.00", "is_active": True},
    )
    await client.post(
        f"{PLANTS_PREFIX}/{plant.id}/pot-sizes",
        json={"name": "Hidden", "price_adjustment": "0.00", "is_active": False},
    )
    client.cookies.clear()

    response = await client.get(f"{STOREFRONT_PREFIX}/plants/{plant.slug}")
    assert response.status_code == 200
    names = [size["name"] for size in response.json()["pot_sizes"]]
    assert names == ["Visible"]
    assert visible.status_code == 201


# --------------------------------------------------------------------------
# Public storefront search
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_search_vietnamese_fields(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"English Only {marker}",
        name_vi=f"Cây Trầu Bà {marker}",
        description="English description without the Vietnamese keyword.",
        description_vi=f"Mô tả nhiệt đới {marker}.",
        price_vi=Decimal("650000.00"),
    )
    await _seed_image(test_db_session, plant, url="https://cdn.example.com/vi.jpg")

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"Trầu Bà {marker}", "locale": "vi"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == f"Trầu Bà {marker}"
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(plant.id)
    assert item["slug"] == plant.slug
    assert item["name_vi"] == f"Cây Trầu Bà {marker}"
    assert item["description_vi"] == f"Mô tả nhiệt đới {marker}."
    assert Decimal(item["price_vi"]) == Decimal("650000.00")
    assert len(item["images"]) == 1


@pytest.mark.asyncio
async def test_public_search_english_fields(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"Monstera Deliciosa {marker}",
        name_vi=f"Cây khác {marker}",
        description=f"A tropical monstera {marker} for indoors.",
        description_vi="Mô tả tiếng Việt không chứa từ khóa tiếng Anh.",
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"Monstera Deliciosa {marker}", "locale": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == f"Monstera Deliciosa {marker}"
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(plant.id)
    assert body["items"][0]["name"] == f"Monstera Deliciosa {marker}"


@pytest.mark.asyncio
async def test_public_search_partial_keyword_matching(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"ZZ Plant Super {marker}",
        description=f"Hardy indoor zzplant-{marker} variety.",
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"zzplant-{marker}", "locale": "en"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(plant.id)


@pytest.mark.asyncio
async def test_public_search_is_case_insensitive(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"Fiddle Leaf Fig {marker}",
        description="Large green leaves.",
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"fiddle leaf fig {marker}", "locale": "en"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(plant.id)


@pytest.mark.asyncio
async def test_public_search_empty_keyword_returns_no_results(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _seed_plant(test_db_session, test_category, is_active=True)

    for q in ("", "   ", "\t"):
        response = await client.get(
            f"{STOREFRONT_PREFIX}/plants/search",
            params={"q": q, "locale": "en"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["query"] == ""
        assert body["total"] == 0
        assert body["items"] == []


@pytest.mark.asyncio
async def test_public_search_no_matching_results(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name="Snake Plant",
        name_vi="Cây Lưỡi Hổ",
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"no-such-plant-{uuid4().hex}", "locale": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_public_search_excludes_inactive_plants(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    inactive = await _seed_plant(
        test_db_session,
        test_category,
        is_active=False,
        name=f"Hidden Searchable {marker}",
        name_vi=f"Ẩn Tìm Kiếm {marker}",
    )
    active = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"Visible Searchable {marker}",
        name_vi=f"Hiện Tìm Kiếm {marker}",
    )

    en = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"Searchable {marker}", "locale": "en"},
    )
    assert en.status_code == 200
    en_ids = [item["id"] for item in en.json()["items"]]
    assert str(active.id) in en_ids
    assert str(inactive.id) not in en_ids

    vi = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"Tìm Kiếm {marker}", "locale": "vi"},
    )
    assert vi.status_code == 200
    vi_ids = [item["id"] for item in vi.json()["items"]]
    assert str(active.id) in vi_ids
    assert str(inactive.id) not in vi_ids


@pytest.mark.asyncio
async def test_public_search_rejects_invalid_locale(client: AsyncClient) -> None:
    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": "monstera", "locale": "fr"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_public_search_locale_does_not_cross_match(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    """English keywords must not match Vietnamese-only copy, and vice versa."""
    marker = uuid4().hex[:8]
    await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"EnglishUniqueName {marker}",
        name_vi=f"TenTiengVietDuyNhat {marker}",
        description="plain english copy",
        description_vi="ban sao tieng viet",
    )

    vi_miss = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"EnglishUniqueName {marker}", "locale": "vi"},
    )
    assert vi_miss.json()["total"] == 0

    en_miss = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"TenTiengVietDuyNhat {marker}", "locale": "en"},
    )
    assert en_miss.json()["total"] == 0


@pytest.mark.asyncio
async def test_public_search_treats_like_metacharacters_literally(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    plant = await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"100% Humidity {marker}",
        description="Safe under_score plant.",
    )
    await _seed_plant(
        test_db_session,
        test_category,
        is_active=True,
        name=f"100X Humidity {marker}",
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/search",
        params={"q": f"100% Humidity {marker}", "locale": "en"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(plant.id)
