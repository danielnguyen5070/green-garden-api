"""Categories API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.category import Category
from app.models.plant import Plant


AUTH_PREFIX = "/api/v1/auth"
CATEGORIES_PREFIX = "/api/v1/categories"
STOREFRONT_PREFIX = "/api/v1/storefront"


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _category_payload(**overrides: object) -> dict:
    unique = uuid4().hex[:8]
    payload: dict = {
        "name": f"Indoor Plants {unique}",
        "slug": f"indoor-plants-{unique}",
        "description": "Plants suitable for indoor spaces.",
        "image_url": "https://example.com/indoor-plants.jpg",
        "sort_order": 1,
        "is_active": True,
    }
    payload.update(overrides)
    return payload


async def _create_category(client: AsyncClient, **overrides: object) -> dict:
    response = await client.post(CATEGORIES_PREFIX, json=_category_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_category(session: AsyncSession, **overrides: object) -> Category:
    unique = uuid4().hex[:8]
    values: dict = {
        "name": f"Seeded Category {unique}",
        "slug": f"seeded-category-{unique}",
        "description": "Seeded category.",
        "image_url": None,
        "sort_order": 0,
        "is_active": True,
    }
    values.update(overrides)
    category = Category(**values)
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_categories_unauthenticated(client: AsyncClient) -> None:
    response = await client.get(CATEGORIES_PREFIX)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_category_unauthenticated(client: AsyncClient) -> None:
    response = await client.post(CATEGORIES_PREFIX, json=_category_payload())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_category_unauthenticated(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    category = await _seed_category(test_db_session)
    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{category.id}",
        json={"name": "Hijacked"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_category_status_unauthenticated(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    category = await _seed_category(test_db_session)
    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{category.id}/status",
        json={"is_active": False},
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_category_success(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    payload = _category_payload()
    response = await client.post(CATEGORIES_PREFIX, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == payload["name"]
    assert body["slug"] == payload["slug"]
    assert body["description"] == payload["description"]
    assert body["image_url"] == payload["image_url"]
    assert body["sort_order"] == 1
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_category_defaults(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    unique = uuid4().hex[:8]
    response = await client.post(
        CATEGORIES_PREFIX,
        json={"name": f"Minimal {unique}", "slug": f"minimal-{unique}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["is_active"] is True
    assert body["sort_order"] == 0
    assert body["description"] is None
    assert body["image_url"] is None


@pytest.mark.asyncio
async def test_create_category_normalizes_name_and_slug(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    unique = uuid4().hex[:8]
    body = await _create_category(
        client,
        name=f"  Outdoor Plants {unique}  ",
        slug=f"  Outdoor Plants {unique}  ",
    )
    assert body["name"] == f"Outdoor Plants {unique}"
    assert body["slug"] == f"outdoor-plants-{unique}".lower()


@pytest.mark.asyncio
async def test_create_category_duplicate_slug(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    existing = await _create_category(client)
    response = await client.post(
        CATEGORIES_PREFIX,
        json=_category_payload(slug=existing["slug"]),
    )
    assert response.status_code == 409
    assert "slug" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_category_empty_name(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(CATEGORIES_PREFIX, json=_category_payload(name="   "))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_category_invalid_image_url(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        CATEGORIES_PREFIX,
        json=_category_payload(image_url="not-a-url"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_category_unusable_slug(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(CATEGORIES_PREFIX, json=_category_payload(slug="!!!"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_category_negative_sort_order(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        CATEGORIES_PREFIX,
        json=_category_payload(sort_order=-1),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# List
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_categories_pagination(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    for index in range(3):
        await _seed_category(
            test_db_session,
            name=f"Paged {marker} {index}",
            slug=f"paged-{marker}-{index}",
        )

    first = await client.get(
        CATEGORIES_PREFIX,
        params={"search": marker, "page": 1, "page_size": 2},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2

    second = await client.get(
        CATEGORIES_PREFIX,
        params={"search": marker, "page": 2, "page_size": 2},
    )
    assert len(second.json()["items"]) == 1


@pytest.mark.asyncio
async def test_list_categories_invalid_page_size(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(CATEGORIES_PREFIX, params={"page_size": 500})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_categories_search_by_name_and_slug(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    target = await _seed_category(
        test_db_session,
        name=f"Findable Category {marker}",
        slug=f"findable-category-{marker}",
    )
    await _seed_category(test_db_session)

    by_name = await client.get(
        CATEGORIES_PREFIX,
        params={"search": f"Findable Category {marker}"},
    )
    assert [item["id"] for item in by_name.json()["items"]] == [str(target.id)]

    by_slug = await client.get(
        CATEGORIES_PREFIX,
        params={"search": f"findable-category-{marker}"},
    )
    assert [item["id"] for item in by_slug.json()["items"]] == [str(target.id)]


@pytest.mark.asyncio
async def test_list_categories_active_filter(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    enabled = await _seed_category(
        test_db_session,
        name=f"Filter {marker} on",
        slug=f"filter-{marker}-on",
        is_active=True,
    )
    disabled = await _seed_category(
        test_db_session,
        name=f"Filter {marker} off",
        slug=f"filter-{marker}-off",
        is_active=False,
    )

    active_only = await client.get(
        CATEGORIES_PREFIX,
        params={"search": marker, "is_active": "true"},
    )
    assert [item["id"] for item in active_only.json()["items"]] == [str(enabled.id)]

    inactive_only = await client.get(
        CATEGORIES_PREFIX,
        params={"search": marker, "is_active": "false"},
    )
    assert [item["id"] for item in inactive_only.json()["items"]] == [str(disabled.id)]

    both = await client.get(CATEGORIES_PREFIX, params={"search": marker})
    assert both.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_categories_ordering(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    marker = uuid4().hex[:8]
    last = await _seed_category(
        test_db_session,
        name=f"Order {marker} last",
        slug=f"order-{marker}-last",
        sort_order=9,
    )
    first = await _seed_category(
        test_db_session,
        name=f"Order {marker} first",
        slug=f"order-{marker}-first",
        sort_order=1,
    )
    middle = await _seed_category(
        test_db_session,
        name=f"Order {marker} middle",
        slug=f"order-{marker}-middle",
        sort_order=5,
    )

    response = await client.get(CATEGORIES_PREFIX, params={"search": marker})
    assert [item["id"] for item in response.json()["items"]] == [
        str(first.id),
        str(middle.id),
        str(last.id),
    ]


# --------------------------------------------------------------------------
# Get
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_category(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_category(client)

    response = await client.get(f"{CATEGORIES_PREFIX}/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["slug"] == created["slug"]


@pytest.mark.asyncio
async def test_get_inactive_category_visible_to_admin(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    await _login(client, active_admin)
    category = await _seed_category(test_db_session, is_active=False)

    response = await client.get(f"{CATEGORIES_PREFIX}/{category.id}")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_get_category_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{CATEGORIES_PREFIX}/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


@pytest.mark.asyncio
async def test_get_category_invalid_uuid(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{CATEGORIES_PREFIX}/not-a-uuid")
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Update
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_category_success(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_category(client)
    new_slug = f"renamed-{uuid4().hex[:8]}"

    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{created['id']}",
        json={
            "name": "Renamed Category",
            "slug": new_slug,
            "sort_order": 7,
            "description": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Category"
    assert body["slug"] == new_slug
    assert body["sort_order"] == 7
    assert body["description"] is None
    assert body["image_url"] == created["image_url"]


@pytest.mark.asyncio
async def test_update_category_duplicate_slug(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    first = await _create_category(client)
    second = await _create_category(client)

    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{second['id']}",
        json={"slug": first["slug"]},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_category_same_slug_is_allowed(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_category(client)

    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{created['id']}",
        json={"slug": created["slug"], "name": "Same Slug"},
    )
    assert response.status_code == 200
    assert response.json()["slug"] == created["slug"]


@pytest.mark.asyncio
async def test_update_category_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{uuid4()}",
        json={"name": "Nope"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_category_invalid_data(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_category(client)

    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{created['id']}",
        json={"sort_order": -3},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_and_activate_category(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    created = await _create_category(client)

    deactivated = await client.patch(
        f"{CATEGORIES_PREFIX}/{created['id']}/status",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    activated = await client.patch(
        f"{CATEGORIES_PREFIX}/{created['id']}/status",
        json={"is_active": True},
    )
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True


@pytest.mark.asyncio
async def test_category_status_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{uuid4()}/status",
        json={"is_active": False},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_deactivating_category_keeps_plants_intact(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    """Deactivation is allowed and must not touch the plants in the category."""
    await _login(client, active_admin)
    category = await _seed_category(test_db_session)
    unique = uuid4().hex[:8]
    plant = Plant(
        category_id=category.id,
        name=f"Kept Plant {unique}",
        slug=f"kept-plant-{unique}",
        price=Decimal("1000.00"),
        stock=2,
        sku=f"KEEP-{unique}".upper(),
        is_active=True,
    )
    test_db_session.add(plant)
    await test_db_session.commit()
    await test_db_session.refresh(plant)

    response = await client.patch(
        f"{CATEGORIES_PREFIX}/{category.id}/status",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    still_there = await client.get(f"/api/v1/plants/{plant.id}")
    assert still_there.status_code == 200
    body = still_there.json()
    assert body["category_id"] == str(category.id)
    assert body["is_active"] is True


# --------------------------------------------------------------------------
# Public storefront
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_categories_accessible_without_auth(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    category = await _seed_category(test_db_session, is_active=True)

    response = await client.get(
        f"{STOREFRONT_PREFIX}/categories",
        params={"search": category.slug},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(category.id)]
    for item in items:
        assert "is_active" not in item
        assert "created_at" not in item
        assert "updated_at" not in item


@pytest.mark.asyncio
async def test_public_categories_hide_inactive(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    enabled = await _seed_category(
        test_db_session,
        name=f"Public {marker} on",
        slug=f"public-{marker}-on",
        is_active=True,
    )
    disabled = await _seed_category(
        test_db_session,
        name=f"Public {marker} off",
        slug=f"public-{marker}-off",
        is_active=False,
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/categories",
        params={"search": marker},
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert str(enabled.id) in ids
    assert str(disabled.id) not in ids
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_public_categories_ordering(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    second = await _seed_category(
        test_db_session,
        name=f"Nav {marker} b",
        slug=f"nav-{marker}-b",
        sort_order=2,
    )
    first = await _seed_category(
        test_db_session,
        name=f"Nav {marker} a",
        slug=f"nav-{marker}-a",
        sort_order=1,
    )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/categories",
        params={"search": marker},
    )
    assert [item["id"] for item in response.json()["items"]] == [
        str(first.id),
        str(second.id),
    ]
