"""Index / update / delete blog knowledge in Weaviate.

Blog SQLAlchemy models are not required yet — pass any object with the expected
attributes (`id`, `slug`, `title`/`content` and optional `_vi` fields).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.services.ai.knowledge.builder import (
    bilingual_chunks,
    blog_title,
    build_blog_knowledge_text,
)
from app.services.ai.knowledge.weaviate import (
    KnowledgeSourceType,
    delete_knowledge_by_source,
    ensure_knowledge_collection,
    get_weaviate_client,
    upsert_knowledge_objects,
)

logger = logging.getLogger(__name__)


def _blog_chunks(blog: Any) -> list[dict[str, Any]]:
    return bilingual_chunks(
        source_type=KnowledgeSourceType.BLOG,
        source=blog,
        build_text=build_blog_knowledge_text,
        build_title=blog_title,
    )


def index_blog(
    blog: Any,
    *,
    settings: Settings | None = None,
) -> int:
    """Create (or replace) Weaviate knowledge for a blog post. Returns object count."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return 0

    chunks = _blog_chunks(blog)
    if not chunks:
        delete_blog_knowledge(blog.id, settings=cfg)
        return 0

    client = get_weaviate_client(cfg)
    ensure_knowledge_collection(client, cfg)
    delete_knowledge_by_source(
        source_type=KnowledgeSourceType.BLOG,
        source_id=blog.id,
        client=client,
        settings=cfg,
    )
    return upsert_knowledge_objects(chunks, client=client, settings=cfg)


def update_blog_knowledge(
    blog: Any,
    *,
    settings: Settings | None = None,
) -> int:
    """Re-index blog knowledge after PostgreSQL source data changes."""
    return index_blog(blog, settings=settings)


def delete_blog_knowledge(
    blog_id: uuid.UUID | str,
    *,
    settings: Settings | None = None,
) -> None:
    """Remove all Weaviate knowledge objects for a blog post."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        return
    delete_knowledge_by_source(
        source_type=KnowledgeSourceType.BLOG,
        source_id=blog_id,
        settings=cfg,
    )


async def reindex_all_blogs(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    blogs: Sequence[Any] | None = None,
) -> int:
    """Re-index blog rows. Pass `blogs` or load from a future Blog model if present."""
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        logger.warning("Weaviate disabled; skipping blog reindex")
        return 0

    rows = list(blogs) if blogs is not None else await _load_blogs(session)
    if not rows:
        logger.info("No blog records to index")
        return 0

    total = 0
    for blog in rows:
        is_active = getattr(blog, "is_active", True)
        is_published = getattr(blog, "is_published", True)
        if is_active is False or is_published is False:
            delete_blog_knowledge(blog.id, settings=cfg)
            continue
        total += index_blog(blog, settings=cfg)
    return total


async def _load_blogs(session: AsyncSession) -> list[Any]:
    try:
        from sqlalchemy import select

        from app.models.blog import Blog  # type: ignore[attr-defined]
    except ImportError:
        logger.info("Blog model not available yet; skipping blog reindex")
        return []

    result = await session.execute(select(Blog))
    return list(result.scalars().all())
