"""Index / update / delete plant knowledge in Weaviate (`PlantKnowledge`).

PostgreSQL remains the source of truth. This module only mirrors chunked
knowledge for active plants — never price, stock, SKU, or other business fields.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.plant import Plant
from app.services.ai.knowledge.builder import prepare_plant_chunks
from app.services.ai.knowledge.weaviate import (
    KnowledgeSourceType,
    PLANT_COLLECTION_NAME,
    delete_plant_knowledge_by_source,
    ensure_plant_knowledge_collection,
    get_weaviate_client,
    knowledge_object_uuid,
    upsert_plant_knowledge_objects,
)

logger = logging.getLogger(__name__)


def _section_chunk_key(section: str | None) -> str:
    """Stable ASCII slug for a Markdown section label (deterministic chunk IDs)."""
    if not section:
        return "body"
    normalized = unicodedata.normalize("NFKD", section)
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return (slug or "body")[:80]


def plant_chunks_to_weaviate_objects(plant: Plant) -> list[dict[str, Any]]:
    """Map ``prepare_plant_chunks`` output to Weaviate upsert payloads."""
    prepared = prepare_plant_chunks(plant)
    counters: dict[tuple[str, str], int] = {}
    objects: list[dict[str, Any]] = []

    for chunk in prepared:
        locale = chunk["locale"]
        section_key = _section_chunk_key(chunk.get("section"))
        counter_key = (locale, section_key)
        index = counters.get(counter_key, 0)
        counters[counter_key] = index + 1
        chunk_id = f"{section_key}:{index}"

        objects.append(
            {
                "uuid": knowledge_object_uuid(
                    source_type=KnowledgeSourceType.PLANT,
                    source_id=plant.id,
                    chunk_id=chunk_id,
                    locale=locale,
                ),
                "source_id": plant.id,
                "source_type": KnowledgeSourceType.PLANT.value,
                "chunk_id": chunk_id,
                "locale": locale,
                "plant_id": str(plant.id),
                "title": chunk["title"],
                "slug": chunk["slug"],
                "section": chunk.get("section") or "",
                "content": chunk["content"],
                "name": getattr(plant, "name", None) or "",
                "name_vi": getattr(plant, "name_vi", None) or "",
            }
        )
    return objects


def _plant_chunks(plant: Plant) -> list[dict[str, Any]]:
    """Build Weaviate payloads from prepared plant chunks."""
    return plant_chunks_to_weaviate_objects(plant)


def index_plant(
    plant: Plant,
    *,
    settings: Settings | None = None,
) -> int:
    """Replace Weaviate knowledge for an active plant. Returns object count.

    Flow: delete existing ``PlantKnowledge`` chunks for this plant, then upsert
    freshly prepared chunks. Inactive plants are removed instead of indexed.
    """
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return 0

    if not plant.is_active:
        delete_plant_knowledge(plant.id, settings=cfg)
        return 0

    chunks = _plant_chunks(plant)
    client = get_weaviate_client(cfg)
    ensure_plant_knowledge_collection(client, cfg)

    # Replace-all so removed sections / locales cannot leave stale objects.
    delete_plant_knowledge_by_source(
        source_id=plant.id,
        client=client,
        settings=cfg,
    )
    if not chunks:
        logger.info(
            "Plant knowledge cleared (no chunks) plant_id=%s collection=%s",
            plant.id,
            PLANT_COLLECTION_NAME,
        )
        return 0

    count = upsert_plant_knowledge_objects(chunks, client=client, settings=cfg)
    logger.info(
        "Plant knowledge indexed plant_id=%s collection=%s chunks=%s",
        plant.id,
        PLANT_COLLECTION_NAME,
        count,
    )
    return count


def update_plant_knowledge(
    plant: Plant,
    *,
    settings: Settings | None = None,
) -> int:
    """Re-index plant knowledge after PostgreSQL source data changes."""
    return index_plant(plant, settings=settings)


def delete_plant_knowledge(
    plant_id: uuid.UUID | str,
    *,
    settings: Settings | None = None,
) -> None:
    """Remove all ``PlantKnowledge`` objects for a plant."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return
    try:
        delete_plant_knowledge_by_source(source_id=plant_id, settings=cfg)
        logger.info(
            "Plant knowledge deleted plant_id=%s collection=%s",
            plant_id,
            PLANT_COLLECTION_NAME,
        )
    except Exception:
        logger.exception(
            "Failed to delete plant knowledge plant_id=%s collection=%s",
            plant_id,
            PLANT_COLLECTION_NAME,
        )
        raise


def sync_plant_knowledge(
    plant: Plant,
    *,
    settings: Settings | None = None,
) -> int:
    """Index active plants; remove knowledge when inactive or empty."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return 0
    if not plant.is_active:
        delete_plant_knowledge(plant.id, settings=cfg)
        return 0
    return index_plant(plant, settings=cfg)


def sync_plant_knowledge_safe(plant: Plant) -> None:
    """Best-effort sync used from plant write paths — never fails the DB commit."""
    plant_id = getattr(plant, "id", None)
    try:
        count = sync_plant_knowledge(plant)
        logger.debug(
            "Plant knowledge sync ok plant_id=%s is_active=%s chunks=%s",
            plant_id,
            getattr(plant, "is_active", None),
            count,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to sync plant knowledge with Weaviate "
            "plant_id=%s is_active=%s collection=%s",
            plant_id,
            getattr(plant, "is_active", None),
            PLANT_COLLECTION_NAME,
        )


async def reindex_all_plants(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    active_only: bool = True,
) -> int:
    """Re-index plants from PostgreSQL. Returns number of Weaviate objects written."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        logger.warning("Weaviate disabled; skipping plant reindex")
        return 0

    stmt = select(Plant)
    if active_only:
        stmt = stmt.where(Plant.is_active.is_(True))
    result = await session.execute(stmt)
    plants = list(result.scalars().all())

    total = 0
    for plant in plants:
        total += index_plant(plant, settings=cfg)
    return total
