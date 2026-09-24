"""Weaviate semantic search over `PlantKnowledge` chunks.

PostgreSQL remains the source of truth for price/stock — this module never
returns those fields.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings, get_settings
from app.services.ai.knowledge.weaviate import (
    PLANT_COLLECTION_NAME,
    get_weaviate_client,
)

logger = logging.getLogger(__name__)


def search_plant_knowledge(
    query: str,
    *,
    limit: int | None = None,
    locale: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Retrieve relevant plant-knowledge chunks for RAG (care, traits, etc.)."""
    cleaned = (query or "").strip()
    if not cleaned:
        return {"found": False, "chunks": [], "error": "Empty search query"}

    cfg = settings or get_settings()
    top_k = limit if limit is not None else max(1, int(cfg.rag_top_k))
    if not cfg.weaviate_enabled:
        return {
            "found": False,
            "chunks": [],
            "error": "Plant knowledge search is temporarily unavailable",
        }

    try:
        client = get_weaviate_client(cfg)
        if not client.collections.exists(PLANT_COLLECTION_NAME):
            return {"found": False, "chunks": [], "error": "No plant knowledge indexed yet"}

        from weaviate.classes.query import Filter, MetadataQuery

        collection = client.collections.get(PLANT_COLLECTION_NAME)
        filters = None
        if locale in {"en", "vi"}:
            filters = Filter.by_property("locale").equal(locale)

        result = None
        if cfg.openai_api_key:
            try:
                result = collection.query.near_text(
                    query=cleaned,
                    limit=top_k,
                    filters=filters,
                    return_metadata=MetadataQuery(distance=True),
                )
            except Exception:  # noqa: BLE001
                logger.exception("near_text failed; falling back to bm25")

        if result is None:
            result = collection.query.bm25(
                query=cleaned,
                limit=top_k,
                filters=filters,
            )

        chunks: list[dict[str, Any]] = []
        for obj in result.objects:
            props = obj.properties or {}
            content = str(props.get("content") or "").strip()
            if not content:
                continue
            chunks.append(
                {
                    "title": props.get("title") or "",
                    "slug": props.get("slug") or "",
                    "locale": props.get("locale") or "",
                    "section": props.get("section") or "",
                    "content": content,
                }
            )

        return {"found": bool(chunks), "chunks": chunks, "query": cleaned}
    except Exception:  # noqa: BLE001
        logger.exception("Plant knowledge search failed query=%r", cleaned)
        return {
            "found": False,
            "chunks": [],
            "error": "Plant knowledge search failed",
        }
