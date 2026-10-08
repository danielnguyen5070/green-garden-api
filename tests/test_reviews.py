"""Shop and plant review API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.admins.models import Admin
from app.features.categories.models import Category
from app.features.plants.models import Plant
from app.features.reviews.models import Review, ReviewStatus

AUTH_PREFIX = "/api/v1/auth"
REVIEWS_PREFIX = "/api/v1/reviews"
STOREFRONT_PREFIX = "/api/v1/storefront"


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _review_payload(**overrides: object) -> dict:
    payload = {
        "name": "Nguyen Van A",
        "rating": 5,
        "content": "Cây đẹp, giao hàng nhanh.",
        "website": "",
        "form_elapsed_ms": 5000,
    }
    payload.update(overrides)
    return payload


async def _seed_review(
    session: AsyncSession,
    **overrides: object,
) -> Review:
    values: dict = {
        "name": f"Reviewer {uuid4().hex[:8]}",
        "rating": 5,
        "content": "Great shop.",
        "status": ReviewStatus.PENDING,
    }
    values.update(overrides)
    review = Review(**values)
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return review


async def _seed_plant(
    session: AsyncSession,
    category: Category,
    **overrides: object,
) -> Plant:
    unique = uuid4().hex[:8]
    values: dict = {
        "category_id": category.id,
        "name": f"Reviewed {unique}",
        "name_vi": f"Cây {unique}",
        "slug": f"reviewed-{unique}",
        "price": Decimal("100000.00"),
        "stock": 5,
        "sku": f"REV-{unique}",
        "is_active": True,
    }
    values.update(overrides)
    plant = Plant(**values)
    session.add(plant)
    await session.commit()
    await session.refresh(plant)
    return plant


# --------------------------------------------------------------------------
# Public storefront
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_submit_review_without_auth(client: AsyncClient) -> None:
    response = await client.post(
        f"{STOREFRONT_PREFIX}/reviews",
        json=_review_payload(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Nguyen Van A"
    assert body["rating"] == 5
    assert body["content"] == "Cây đẹp, giao hàng nhanh."
    assert body["status"] == "pending"
    assert "id" in body


@pytest.mark.asyncio
async def test_public_submit_review_strips_whitespace(client: AsyncClient) -> None:
    response = await client.post(
        f"{STOREFRONT_PREFIX}/reviews",
        json=_review_payload(name="  Lan  ", content="  Rất hài lòng.  "),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Lan"
    assert body["content"] == "Rất hài lòng."


@pytest.mark.asyncio
async def test_public_submit_review_rejects_invalid_rating(
    client: AsyncClient,
) -> None:
    for rating in (0, 6):
        response = await client.post(
            f"{STOREFRONT_PREFIX}/reviews",
            json=_review_payload(rating=rating),
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_public_submit_review_rejects_empty_fields(
    client: AsyncClient,
) -> None:
    for payload in (
        _review_payload(name="   "),
        _review_payload(content=""),
        _review_payload(content="   "),
    ):
        response = await client.post(f"{STOREFRONT_PREFIX}/reviews", json=payload)
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_public_list_returns_only_approved_reviews(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    approved = await _seed_review(
        test_db_session,
        name=f"Approved {marker}",
        content=f"Approved content {marker}",
        status=ReviewStatus.APPROVED,
    )
    await _seed_review(
        test_db_session,
        name=f"Pending {marker}",
        content=f"Pending content {marker}",
        status=ReviewStatus.PENDING,
    )
    await _seed_review(
        test_db_session,
        name=f"Rejected {marker}",
        content=f"Rejected content {marker}",
        status=ReviewStatus.REJECTED,
    )

    response = await client.get(f"{STOREFRONT_PREFIX}/reviews")
    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert str(approved.id) in ids
    assert all(
        item["name"].startswith("Approved") or marker not in item["name"]
        for item in body["items"]
        if marker in item.get("name", "") or marker in item.get("content", "")
    )
    matching = [item for item in body["items"] if marker in item["name"]]
    assert len(matching) == 1
    assert matching[0]["id"] == str(approved.id)
    assert "status" not in matching[0]
    assert "updated_at" not in matching[0]
    assert "created_at" in matching[0]


@pytest.mark.asyncio
async def test_public_list_is_paginated(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    for i in range(3):
        await _seed_review(
            test_db_session,
            name=f"Page {marker} {i}",
            content=f"Page content {marker} {i}",
            status=ReviewStatus.APPROVED,
        )

    response = await client.get(
        f"{STOREFRONT_PREFIX}/reviews",
        params={"page": 1, "page_size": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] >= 3
    assert len(body["items"]) == 2


# --------------------------------------------------------------------------
# Admin moderation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_reviews_requires_auth(client: AsyncClient) -> None:
    response = await client.get(REVIEWS_PREFIX)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_and_filter_by_status(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    marker = uuid4().hex[:8]
    pending = await _seed_review(
        test_db_session,
        name=f"Pending Admin {marker}",
        status=ReviewStatus.PENDING,
    )
    approved = await _seed_review(
        test_db_session,
        name=f"Approved Admin {marker}",
        status=ReviewStatus.APPROVED,
    )

    await _login(client, active_admin)

    all_rows = await client.get(
        REVIEWS_PREFIX,
        params={"search": marker},
    )
    assert all_rows.status_code == 200
    assert all_rows.json()["total"] == 2

    pending_only = await client.get(
        REVIEWS_PREFIX,
        params={"search": marker, "status": "pending"},
    )
    assert pending_only.status_code == 200
    assert pending_only.json()["total"] == 1
    assert pending_only.json()["items"][0]["id"] == str(pending.id)

    approved_only = await client.get(
        REVIEWS_PREFIX,
        params={"search": marker, "status": "approved"},
    )
    assert approved_only.status_code == 200
    assert approved_only.json()["total"] == 1
    assert approved_only.json()["items"][0]["id"] == str(approved.id)


@pytest.mark.asyncio
async def test_admin_get_review_detail(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    review = await _seed_review(test_db_session, status=ReviewStatus.PENDING)
    await _login(client, active_admin)

    response = await client.get(f"{REVIEWS_PREFIX}/{review.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(review.id)
    assert body["status"] == "pending"
    assert body["rating"] == review.rating


@pytest.mark.asyncio
async def test_admin_get_review_not_found(
    client: AsyncClient,
    active_admin: Admin,
) -> None:
    await _login(client, active_admin)
    response = await client.get(f"{REVIEWS_PREFIX}/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_approve_review_makes_it_public(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    review = await _seed_review(
        test_db_session,
        name="Moderation Flow",
        content="Please approve me.",
        status=ReviewStatus.PENDING,
    )

    public_before = await client.get(f"{STOREFRONT_PREFIX}/reviews")
    assert str(review.id) not in [item["id"] for item in public_before.json()["items"]]

    await _login(client, active_admin)
    patched = await client.patch(
        f"{REVIEWS_PREFIX}/{review.id}/status",
        json={"status": "approved"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "approved"
    client.cookies.clear()

    public_after = await client.get(f"{STOREFRONT_PREFIX}/reviews")
    ids = [item["id"] for item in public_after.json()["items"]]
    assert str(review.id) in ids


@pytest.mark.asyncio
async def test_admin_reject_review_keeps_it_off_storefront(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    review = await _seed_review(
        test_db_session,
        name="Reject Flow",
        content="Should stay hidden.",
        status=ReviewStatus.PENDING,
    )

    await _login(client, active_admin)
    patched = await client.patch(
        f"{REVIEWS_PREFIX}/{review.id}/status",
        json={"status": "rejected"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "rejected"
    client.cookies.clear()

    public = await client.get(f"{STOREFRONT_PREFIX}/reviews")
    assert str(review.id) not in [item["id"] for item in public.json()["items"]]


@pytest.mark.asyncio
async def test_admin_status_update_requires_auth(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    review = await _seed_review(test_db_session)
    response = await client.patch(
        f"{REVIEWS_PREFIX}/{review.id}/status",
        json={"status": "approved"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_status_update_rejects_invalid_status(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
) -> None:
    review = await _seed_review(test_db_session)
    await _login(client, active_admin)
    response = await client.patch(
        f"{REVIEWS_PREFIX}/{review.id}/status",
        json={"status": "published"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Plant reviews
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_submit_plant_review(
    client: AsyncClient,
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)

    response = await client.post(
        f"{STOREFRONT_PREFIX}/plants/{plant.slug}/reviews",
        json=_review_payload(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["plant_id"] == str(plant.id)
    assert body["plant"] == {
        "id": str(plant.id),
        "name": plant.name,
        "name_vi": plant.name_vi,
        "slug": plant.slug,
    }


@pytest.mark.asyncio
async def test_public_shop_review_has_no_plant(client: AsyncClient) -> None:
    response = await client.post(
        f"{STOREFRONT_PREFIX}/reviews",
        json=_review_payload(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["plant_id"] is None
    assert body["plant"] is None


@pytest.mark.asyncio
async def test_plant_reviews_404_for_unknown_or_inactive_plant(
    client: AsyncClient,
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    inactive = await _seed_plant(test_db_session, test_category, is_active=False)

    for slug in (f"missing-{uuid4().hex[:8]}", inactive.slug):
        listed = await client.get(f"{STOREFRONT_PREFIX}/plants/{slug}/reviews")
        assert listed.status_code == 404
        submitted = await client.post(
            f"{STOREFRONT_PREFIX}/plants/{slug}/reviews",
            json=_review_payload(),
        )
        assert submitted.status_code == 404


@pytest.mark.asyncio
async def test_public_plant_reviews_list_only_approved_with_summary(
    client: AsyncClient,
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    other = await _seed_plant(test_db_session, test_category)

    five = await _seed_review(
        test_db_session, plant_id=plant.id, rating=5, status=ReviewStatus.APPROVED
    )
    four = await _seed_review(
        test_db_session, plant_id=plant.id, rating=4, status=ReviewStatus.APPROVED
    )
    another_five = await _seed_review(
        test_db_session, plant_id=plant.id, rating=5, status=ReviewStatus.APPROVED
    )
    await _seed_review(
        test_db_session, plant_id=plant.id, rating=1, status=ReviewStatus.PENDING
    )
    await _seed_review(
        test_db_session, plant_id=plant.id, rating=1, status=ReviewStatus.REJECTED
    )
    await _seed_review(
        test_db_session, plant_id=other.id, rating=2, status=ReviewStatus.APPROVED
    )
    await _seed_review(test_db_session, rating=3, status=ReviewStatus.APPROVED)

    response = await client.get(
        f"{STOREFRONT_PREFIX}/plants/{plant.slug}/reviews",
        params={"page": 1, "page_size": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert {item["id"] for item in body["items"]} <= {
        str(five.id),
        str(four.id),
        str(another_five.id),
    }
    assert body["total_reviews"] == 3
    assert body["average_rating"] == pytest.approx(4.7)
    assert body["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 2}


@pytest.mark.asyncio
async def test_public_plant_reviews_empty_summary(
    client: AsyncClient,
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)

    response = await client.get(f"{STOREFRONT_PREFIX}/plants/{plant.slug}/reviews")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["total_reviews"] == 0
    assert body["average_rating"] == 0
    assert body["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


@pytest.mark.asyncio
async def test_public_shop_list_excludes_plant_reviews(
    client: AsyncClient,
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    plant_review = await _seed_review(
        test_db_session, plant_id=plant.id, status=ReviewStatus.APPROVED
    )
    shop_review = await _seed_review(test_db_session, status=ReviewStatus.APPROVED)

    response = await client.get(
        f"{STOREFRONT_PREFIX}/reviews", params={"page_size": 100}
    )
    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert str(shop_review.id) in ids
    assert str(plant_review.id) not in ids
    assert body["total_reviews"] == body["total"]
    assert sum(body["rating_distribution"].values()) == body["total_reviews"]


@pytest.mark.asyncio
async def test_admin_filter_by_scope_and_plant(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    marker = uuid4().hex[:8]
    plant = await _seed_plant(test_db_session, test_category)
    other = await _seed_plant(test_db_session, test_category)
    plant_review = await _seed_review(
        test_db_session, name=f"Plant {marker}", plant_id=plant.id
    )
    other_review = await _seed_review(
        test_db_session, name=f"Other {marker}", plant_id=other.id
    )
    shop_review = await _seed_review(test_db_session, name=f"Shop {marker}")

    await _login(client, active_admin)

    async def ids_for(**params: str) -> set[str]:
        response = await client.get(
            REVIEWS_PREFIX, params={"search": marker, **params}
        )
        assert response.status_code == 200
        return {item["id"] for item in response.json()["items"]}

    assert await ids_for() == {
        str(plant_review.id),
        str(other_review.id),
        str(shop_review.id),
    }
    assert await ids_for(scope="shop") == {str(shop_review.id)}
    assert await ids_for(scope="plant") == {
        str(plant_review.id),
        str(other_review.id),
    }
    assert await ids_for(plant_id=str(plant.id)) == {str(plant_review.id)}

    listed = await client.get(
        REVIEWS_PREFIX, params={"search": marker, "plant_id": str(plant.id)}
    )
    item = listed.json()["items"][0]
    assert item["plant"]["slug"] == plant.slug
    assert item["plant"]["name"] == plant.name

    invalid = await client.get(REVIEWS_PREFIX, params={"scope": "everything"})
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_admin_approve_plant_review_makes_it_public(
    client: AsyncClient,
    active_admin: Admin,
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    review = await _seed_review(test_db_session, plant_id=plant.id)
    url = f"{STOREFRONT_PREFIX}/plants/{plant.slug}/reviews"

    assert (await client.get(url)).json()["total"] == 0

    await _login(client, active_admin)
    patched = await client.patch(
        f"{REVIEWS_PREFIX}/{review.id}/status",
        json={"status": "approved"},
    )
    assert patched.status_code == 200
    assert patched.json()["plant"]["id"] == str(plant.id)
    client.cookies.clear()

    body = (await client.get(url)).json()
    assert [item["id"] for item in body["items"]] == [str(review.id)]


@pytest.mark.asyncio
async def test_plant_reviews_deleted_with_plant(
    test_db_session: AsyncSession,
    test_category: Category,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    review = await _seed_review(test_db_session, plant_id=plant.id)

    await test_db_session.execute(delete(Plant).where(Plant.id == plant.id))
    await test_db_session.commit()

    remaining = await test_db_session.execute(
        select(Review.id).where(Review.id == review.id)
    )
    assert remaining.scalar_one_or_none() is None
