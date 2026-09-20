"""Website-wide customer review API tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.models.review import Review, ReviewStatus


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
