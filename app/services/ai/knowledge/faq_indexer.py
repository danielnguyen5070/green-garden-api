"""Index / update / delete FAQ knowledge in Weaviate.

FAQ SQLAlchemy models are not required yet — pass any object with the expected
attributes (`id`, `slug`, `question`/`answer` and optional `_vi` fields).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.services.ai.knowledge.builder import (
    bilingual_chunks,
    build_faq_knowledge_text,
    faq_title,
)
from app.services.ai.knowledge.weaviate import (
    KnowledgeSourceType,
    delete_knowledge_by_source,
    ensure_knowledge_collection,
    get_weaviate_client,
    upsert_knowledge_objects,
)

logger = logging.getLogger(__name__)


def _faq_chunks(faq: Any) -> list[dict[str, Any]]:
    return bilingual_chunks(
        source_type=KnowledgeSourceType.FAQ,
        source=faq,
        build_text=build_faq_knowledge_text,
        build_title=faq_title,
    )


def index_faq(
    faq: Any,
    *,
    settings: Settings | None = None,
) -> int:
    """Create (or replace) Weaviate knowledge for an FAQ. Returns object count."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return 0

    chunks = _faq_chunks(faq)
    if not chunks:
        delete_faq_knowledge(faq.id, settings=cfg)
        return 0

    client = get_weaviate_client(cfg)
    ensure_knowledge_collection(client, cfg)
    delete_knowledge_by_source(
        source_type=KnowledgeSourceType.FAQ,
        source_id=faq.id,
        client=client,
        settings=cfg,
    )
    return upsert_knowledge_objects(chunks, client=client, settings=cfg)


def update_faq_knowledge(
    faq: Any,
    *,
    settings: Settings | None = None,
) -> int:
    """Re-index FAQ knowledge after PostgreSQL source data changes."""
    return index_faq(faq, settings=settings)


def delete_faq_knowledge(
    faq_id: uuid.UUID | str,
    *,
    settings: Settings | None = None,
) -> None:
    """Remove all Weaviate knowledge objects for an FAQ."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return
    delete_knowledge_by_source(
        source_type=KnowledgeSourceType.FAQ,
        source_id=faq_id,
        settings=cfg,
    )


async def reindex_all_faqs(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    faqs: Sequence[Any] | None = None,
) -> int:
    """Re-index FAQ rows. Pass `faqs` or load from a future FAQ model if present."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        logger.warning("Weaviate disabled; skipping FAQ reindex")
        return 0

    rows = list(faqs) if faqs is not None else await _load_faqs(session)
    if not rows:
        logger.info("No FAQ records to index")
        return 0

    total = 0
    for faq in rows:
        is_active = getattr(faq, "is_active", True)
        if is_active is False:
            delete_faq_knowledge(faq.id, settings=cfg)
            continue
        total += index_faq(faq, settings=cfg)
    return total


async def _load_faqs(session: AsyncSession) -> list[Any]:
    try:
        from sqlalchemy import select

        from app.models.faq import Faq  # type: ignore[attr-defined]
    except ImportError:
        logger.info("FAQ model not available yet; skipping FAQ reindex")
        return []

    result = await session.execute(select(Faq))
    return list(result.scalars().all())
