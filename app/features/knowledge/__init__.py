"""PostgreSQL → Weaviate knowledge indexing.

PostgreSQL remains the source of truth for catalogue data (including price and
stock). Weaviate stores bilingual knowledge chunks for future RAG search.
"""

from app.features.knowledge.blog_indexer import (
    delete_blog_knowledge,
    index_blog,
    reindex_all_blogs,
    update_blog_knowledge,
)
from app.features.knowledge.faq_indexer import (
    delete_faq_knowledge,
    index_faq,
    load_faq_snapshot,
    reindex_all_faqs,
    update_faq_knowledge,
)
from app.features.knowledge.builder import (
    PlantChunk,
    build_plant_content,
    prepare_plant_chunks,
)
from app.features.knowledge.plant_indexer import (
    delete_plant_knowledge,
    index_plant,
    reindex_all_plants,
    sync_plant_knowledge,
    sync_plant_knowledge_safe,
    update_plant_knowledge,
)
from app.features.knowledge.retriever import (
    search_faq_knowledge,
    search_plant_knowledge,
)
from app.features.knowledge.weaviate import (
    COLLECTION_NAME,
    PLANT_COLLECTION_NAME,
    KnowledgeSourceType,
    close_weaviate_client,
    ensure_knowledge_collection,
    ensure_plant_knowledge_collection,
    get_weaviate_client,
    knowledge_object_uuid,
    upsert_knowledge_objects,
    upsert_plant_knowledge_objects,
)

__all__ = [
    "COLLECTION_NAME",
    "PLANT_COLLECTION_NAME",
    "KnowledgeSourceType",
    "PlantChunk",
    "build_plant_content",
    "close_weaviate_client",
    "delete_blog_knowledge",
    "delete_faq_knowledge",
    "delete_plant_knowledge",
    "ensure_knowledge_collection",
    "ensure_plant_knowledge_collection",
    "get_weaviate_client",
    "index_blog",
    "index_faq",
    "index_plant",
    "knowledge_object_uuid",
    "load_faq_snapshot",
    "prepare_plant_chunks",
    "reindex_all_blogs",
    "reindex_all_faqs",
    "reindex_all_plants",
    "search_faq_knowledge",
    "search_plant_knowledge",
    "sync_plant_knowledge",
    "sync_plant_knowledge_safe",
    "update_blog_knowledge",
    "update_faq_knowledge",
    "update_plant_knowledge",
    "upsert_knowledge_objects",
    "upsert_plant_knowledge_objects",
]
