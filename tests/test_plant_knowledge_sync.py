"""Plant API ↔ Weaviate `PlantKnowledge` synchronization tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.models.admin import Admin
from app.models.category import Category
from app.services.ai.knowledge.plant_indexer import (
    plant_chunks_to_weaviate_objects,
    sync_plant_knowledge,
)
from app.services.ai.knowledge.weaviate import KnowledgeSourceType, knowledge_object_uuid


AUTH_PREFIX = "/api/v1/auth"
PLANTS_PREFIX = "/api/v1/plants"


async def _login(client: AsyncClient, admin: Admin) -> None:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": admin.email, "password": "correct-password"},
    )
    assert response.status_code == 200


def _plant_payload(category: Category, **overrides: object) -> dict:
    unique = uuid.uuid4().hex[:8]
    payload = {
        "category_id": str(category.id),
        "name": f"Monstera {unique}",
        "name_vi": f"Trầu bà {unique}",
        "slug": f"monstera-{unique}",
        "description": "Beautiful tropical plant.",
        "description_vi": "Cây nhiệt đới đẹp.",
        "price": "250000.00",
        "stock": 20,
        "sku": f"MON-{unique}",
        "is_featured": True,
        "is_active": True,
    }
    payload.update(overrides)
    return payload


class _InMemoryPlantKnowledge:
    """Minimal stand-in for the Weaviate `PlantKnowledge` collection."""

    def __init__(self) -> None:
        self.by_plant: dict[str, list[dict[str, Any]]] = {}
        self.delete_calls: list[str] = []
        self.upsert_calls: list[list[dict[str, Any]]] = []

    def delete(self, source_id: uuid.UUID | str, **_: Any) -> None:
        key = str(source_id)
        self.delete_calls.append(key)
        self.by_plant[key] = []

    def upsert(self, objects: list[dict[str, Any]], **_: Any) -> int:
        self.upsert_calls.append(objects)
        if not objects:
            return 0
        plant_id = str(objects[0]["plant_id"])
        self.by_plant[plant_id] = list(objects)
        return len(objects)

    def chunks_for(self, plant_id: str | UUID) -> list[dict[str, Any]]:
        return list(self.by_plant.get(str(plant_id), []))


@pytest.fixture
def plant_knowledge_store(monkeypatch: pytest.MonkeyPatch) -> _InMemoryPlantKnowledge:
    """Enable Weaviate sync and capture PlantKnowledge delete/upsert calls."""
    store = _InMemoryPlantKnowledge()
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "weaviate_enabled", True)

    monkeypatch.setattr(
        "app.services.ai.knowledge.plant_indexer.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.services.ai.knowledge.plant_indexer.get_weaviate_client",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        "app.services.ai.knowledge.plant_indexer.ensure_plant_knowledge_collection",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        "app.services.ai.knowledge.plant_indexer.delete_plant_knowledge_by_source",
        store.delete,
    )
    monkeypatch.setattr(
        "app.services.ai.knowledge.plant_indexer.upsert_plant_knowledge_objects",
        store.upsert,
    )
    yield store
    get_settings.cache_clear()


def _assert_no_business_fields(chunks: list[dict[str, Any]]) -> None:
    for chunk in chunks:
        content = str(chunk.get("content", ""))
        assert "250000" not in content
        for forbidden_key in ("price", "price_vi", "stock", "sku"):
            assert forbidden_key not in chunk
        # Business identifiers must not leak into embeddable text.
        assert "MON-" not in content
        assert "sku" not in content.lower()


@pytest.mark.asyncio
async def test_create_plant_indexes_weaviate(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    plant_knowledge_store: _InMemoryPlantKnowledge,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    plant_id = body["id"]

    chunks = plant_knowledge_store.chunks_for(plant_id)
    assert len(chunks) > 0
    assert plant_knowledge_store.delete_calls  # replace-all before upsert
    assert all(c["plant_id"] == plant_id for c in chunks)
    assert all(c["source_type"] == KnowledgeSourceType.PLANT.value for c in chunks)
    assert all(c["slug"] == body["slug"] for c in chunks)
    assert {c["locale"] for c in chunks} <= {"en", "vi"}
    _assert_no_business_fields(chunks)

    # Deterministic UUIDs from (source, chunk_id, locale)
    for chunk in chunks:
        expected = knowledge_object_uuid(
            source_type=KnowledgeSourceType.PLANT,
            source_id=plant_id,
            chunk_id=chunk["chunk_id"],
            locale=chunk["locale"],
        )
        assert chunk["uuid"] == expected


@pytest.mark.asyncio
async def test_update_plant_replaces_weaviate_chunks(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    plant_knowledge_store: _InMemoryPlantKnowledge,
) -> None:
    await _login(client, active_admin)
    created = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(
            test_category,
            description="Original English description.",
            description_vi="Mô tả gốc.",
        ),
    )
    assert created.status_code == 201
    plant_id = created.json()["id"]
    original = plant_knowledge_store.chunks_for(plant_id)
    assert original
    original_contents = {c["content"] for c in original}
    deletes_after_create = len(plant_knowledge_store.delete_calls)

    updated = await client.patch(
        f"{PLANTS_PREFIX}/{plant_id}",
        json={
            "description": "Updated English description for indexing.",
            "description_vi": "Mô tả mới để đồng bộ Weaviate.",
            "name_vi": "Cây Trầu Bà Mới",
        },
    )
    assert updated.status_code == 200, updated.text

    assert len(plant_knowledge_store.delete_calls) > deletes_after_create
    refreshed = plant_knowledge_store.chunks_for(plant_id)
    assert refreshed
    new_contents = {c["content"] for c in refreshed}
    assert new_contents != original_contents
    assert any("Updated English description" in c for c in new_contents) or any(
        "Mô tả mới" in c for c in new_contents
    )
    _assert_no_business_fields(refreshed)


@pytest.mark.asyncio
async def test_deactivate_plant_deletes_weaviate_chunks(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    plant_knowledge_store: _InMemoryPlantKnowledge,
) -> None:
    await _login(client, active_admin)
    created = await client.post(PLANTS_PREFIX, json=_plant_payload(test_category))
    assert created.status_code == 201
    plant_id = created.json()["id"]
    assert plant_knowledge_store.chunks_for(plant_id)

    deactivated = await client.patch(
        f"{PLANTS_PREFIX}/{plant_id}/status",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert plant_knowledge_store.chunks_for(plant_id) == []
    assert plant_id in plant_knowledge_store.delete_calls


@pytest.mark.asyncio
async def test_reactivate_plant_reindexes_weaviate(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    plant_knowledge_store: _InMemoryPlantKnowledge,
) -> None:
    await _login(client, active_admin)
    created = await client.post(PLANTS_PREFIX, json=_plant_payload(test_category))
    plant_id = created.json()["id"]

    await client.patch(
        f"{PLANTS_PREFIX}/{plant_id}/status",
        json={"is_active": False},
    )
    assert plant_knowledge_store.chunks_for(plant_id) == []

    reactivated = await client.patch(
        f"{PLANTS_PREFIX}/{plant_id}/status",
        json={"is_active": True},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True
    chunks = plant_knowledge_store.chunks_for(plant_id)
    assert len(chunks) > 0
    _assert_no_business_fields(chunks)


@pytest.mark.asyncio
async def test_create_inactive_plant_skips_weaviate_index(
    client: AsyncClient,
    active_admin: Admin,
    test_category: Category,
    plant_knowledge_store: _InMemoryPlantKnowledge,
) -> None:
    await _login(client, active_admin)
    response = await client.post(
        PLANTS_PREFIX,
        json=_plant_payload(test_category, is_active=False),
    )
    assert response.status_code == 201
    plant_id = response.json()["id"]
    assert plant_knowledge_store.chunks_for(plant_id) == []


def test_sync_plant_knowledge_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "weaviate_enabled", False)
    monkeypatch.setattr(
        "app.services.ai.knowledge.plant_indexer.get_settings",
        lambda: settings,
    )
    plant = SimpleNamespace(id=uuid.uuid4(), is_active=True)
    assert sync_plant_knowledge(plant) == 0


def test_plant_chunk_ids_are_deterministic() -> None:
    plant = SimpleNamespace(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        slug="moringa-tree",
        name="Moringa",
        name_vi="Cây Chùm Ngây",
        description="EN desc",
        description_vi="VI desc",
        long_description=None,
        long_description_vi=None,
        plant_type=None,
        difficulty=None,
        growth_rate=None,
        sunlight=None,
        watering=None,
        space_requirement=None,
        indoor_suitable=None,
        outdoor_suitable=None,
        pet_safe=None,
        beginner_friendly=None,
        is_active=True,
    )
    first = plant_chunks_to_weaviate_objects(plant)  # type: ignore[arg-type]
    second = plant_chunks_to_weaviate_objects(plant)  # type: ignore[arg-type]
    assert first == second
    assert len({(o["locale"], o["chunk_id"]) for o in first}) == len(first)
