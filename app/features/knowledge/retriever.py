"""Weaviate semantic search over plant chunks and shop FAQ knowledge.

PostgreSQL remains the source of truth for price/stock — this module never
returns those fields.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings, get_settings
from app.features.knowledge.weaviate import (
    COLLECTION_NAME,
    PLANT_COLLECTION_NAME,
    KnowledgeSourceType,
    get_weaviate_client,
)

logger = logging.getLogger(__name__)

# FAQ entries are short single chunks, so a wider default costs little context.
FAQ_TOP_K = 5


def _search_collection(
    query: str,
    *,
    collection_name: str,
    label: str,
    source_type: KnowledgeSourceType | None = None,
    limit: int | None = None,
    locale: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """near_text (when embeddings are configured) with a BM25 fallback."""
    cleaned = (query or "").strip()
    if not cleaned:
        return {"found": False, "chunks": [], "error": "Empty search query"}

    cfg = settings or get_settings()
    top_k = limit if limit is not None else max(1, int(cfg.rag_top_k))
    title = label[:1].upper() + label[1:]
    if not cfg.weaviate_enabled:
        return {
            "found": False,
            "chunks": [],
            "error": f"{title} search is temporarily unavailable",
        }

    try:
        client = get_weaviate_client(cfg)
        if not client.collections.exists(collection_name):
            return {"found": False, "chunks": [], "error": f"No {label} indexed yet"}

        from weaviate.classes.query import Filter, MetadataQuery

        collection = client.collections.get(collection_name)
        conditions = []
        if source_type is not None:
            conditions.append(
                Filter.by_property("source_type").equal(source_type.value)
            )
        if locale in {"en", "vi"}:
            conditions.append(Filter.by_property("locale").equal(locale))
        filters = Filter.all_of(conditions) if conditions else None

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
        logger.exception("%s search failed query=%r", title, cleaned)
        return {
            "found": False,
            "chunks": [],
            "error": f"{title} search failed",
        }


def search_plant_knowledge(
    query: str,
    *,
    limit: int | None = None,
    locale: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Retrieve relevant plant-knowledge chunks for RAG (care, traits, etc.)."""
    return _search_collection(
        query,
        collection_name=PLANT_COLLECTION_NAME,
        label="plant knowledge",
        limit=limit,
        locale=locale,
        settings=settings,
    )


def search_faq_knowledge(
    query: str,
    *,
    limit: int | None = None,
    locale: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Retrieve shop FAQ entries (ordering, shipping, payment, returns, etc.)."""
    top_k = limit if limit is not None else FAQ_TOP_K
    # Without a locale filter each FAQ matches in both languages; over-fetch so
    # keeping one locale per FAQ still fills `top_k` distinct entries.
    result = _search_collection(
        query,
        collection_name=COLLECTION_NAME,
        label="shop FAQ",
        source_type=KnowledgeSourceType.FAQ,
        limit=top_k * 2,
        locale=locale,
        settings=settings,
    )

    seen: set[str] = set()
    chunks: list[dict[str, Any]] = []
    for chunk in result["chunks"]:
        key = chunk["slug"] or chunk["content"]
        if key in seen:
            continue
        seen.add(key)
        chunks.append(chunk)
    result["chunks"] = chunks[:top_k]
    result["found"] = bool(result["chunks"])
    return result
