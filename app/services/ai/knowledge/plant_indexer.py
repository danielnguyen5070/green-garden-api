"""Index / update / delete plant knowledge in Weaviate."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.plant import Plant
from app.services.ai.knowledge.builder import (
    bilingual_chunks,
    build_plant_content,
    plant_title,
)
from app.services.ai.knowledge.weaviate import (
    KnowledgeSourceType,
    delete_knowledge_by_source,
    ensure_knowledge_collection,
    get_weaviate_client,
    upsert_knowledge_objects,
)

logger = logging.getLogger(__name__)


def _plant_chunks(plant: Plant) -> list[dict[str, Any]]:
    """Build en/vi Weaviate payloads; `content` comes from `build_plant_content`."""
    return bilingual_chunks(
        source_type=KnowledgeSourceType.PLANT,
        source=plant,
        build_text=build_plant_content,
        build_title=plant_title,
        name=plant.name,
        name_vi=plant.name_vi,
    )


def index_plant(
    plant: Plant,
    *,
    settings: Settings | None = None,
) -> int:
    """Create (or replace) Weaviate knowledge for a plant. Returns object count."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return 0

    chunks = _plant_chunks(plant)
    if not chunks:
        delete_plant_knowledge(plant.id, settings=cfg)
        return 0

    client = get_weaviate_client(cfg)
    ensure_knowledge_collection(client, cfg)
    # Replace-all for this source so removed locales / empty locales disappear.
    delete_knowledge_by_source(
        source_type=KnowledgeSourceType.PLANT,
        source_id=plant.id,
        client=client,
        settings=cfg,
    )
    return upsert_knowledge_objects(chunks, client=client, settings=cfg)


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
    """Remove all Weaviate knowledge objects for a plant."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return
    delete_knowledge_by_source(
        source_type=KnowledgeSourceType.PLANT,
        source_id=plant_id,
        settings=cfg,
    )


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
    try:
        sync_plant_knowledge(plant)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to sync plant knowledge for plant_id=%s", getattr(plant, "id", None)
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
