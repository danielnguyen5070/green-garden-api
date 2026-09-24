"""Weaviate client, collection setup, and stable knowledge object IDs."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Iterator
from urllib.parse import urlparse

import weaviate
from weaviate.auth import Auth
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.data import DataObject
from weaviate.collections.collection import Collection
from weaviate.exceptions import UnexpectedStatusCodeError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "NgocNganKnowledge"

# Stable namespace so the same (source, chunk, locale) always maps to one UUID.
_KNOWLEDGE_UUID_NAMESPACE = uuid.UUID("a3f1c8e2-7b4d-4e9a-9c2f-1d6e5b8a0f33")

_client: weaviate.WeaviateClient | None = None


class KnowledgeSourceType(StrEnum):
    PLANT = "plant"
    FAQ = "faq"
    BLOG = "blog"


def knowledge_object_uuid(
    *,
    source_type: KnowledgeSourceType | str,
    source_id: uuid.UUID | str,
    chunk_id: str,
    locale: str,
) -> uuid.UUID:
    """Deterministic Weaviate object UUID from PostgreSQL identity + chunk + locale.

    Never derived from knowledge text content.
    """
    key = f"{source_type}:{source_id}:{chunk_id}:{locale}"
    return uuid.uuid5(_KNOWLEDGE_UUID_NAMESPACE, key)


def _headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.openai_api_key:
        headers["X-OpenAI-Api-Key"] = settings.openai_api_key
    return headers


def _auth(settings: Settings) -> Auth | None:
    if settings.weaviate_api_key:
        return Auth.api_key(settings.weaviate_api_key)
    return None


def get_weaviate_client(
    settings: Settings | None = None,
) -> weaviate.WeaviateClient:
    """Return a shared Weaviate client (lazy connect)."""
    global _client
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        raise RuntimeError("Weaviate is disabled (WEAVIATE_ENABLED=false)")

    if _client is not None and _client.is_connected():
        return _client

    _client = weaviate.connect_to_custom(
        http_host=cfg.weaviate_http_host,
        http_port=cfg.weaviate_http_port,
        http_secure=cfg.weaviate_http_secure,
        grpc_host=cfg.weaviate_grpc_host_resolved(),
        grpc_port=cfg.weaviate_grpc_port,
        grpc_secure=cfg.weaviate_grpc_secure,
        auth_credentials=_auth(cfg),
        headers=_headers(cfg) or None,
        skip_init_checks=False,
    )
    return _client


def close_weaviate_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001 — best-effort shutdown
            logger.exception("Failed to close Weaviate client")
        _client = None


@contextmanager
def weaviate_session(
    settings: Settings | None = None,
) -> Iterator[weaviate.WeaviateClient]:
    """Context manager that yields a connected client without closing the shared one."""
    client = get_weaviate_client(settings)
    yield client


def _vector_config(settings: Settings) -> Any:
    """Prefer OpenAI embeddings when a key is present; otherwise self-provided."""
    if settings.openai_api_key:
        return Configure.Vectors.text2vec_openai(
            model="text-embedding-3-small",
            vectorize_collection_name=False,
            source_properties=["title", "content"],
        )
    return Configure.Vectors.self_provided()


def ensure_knowledge_collection(
    client: weaviate.WeaviateClient | None = None,
    settings: Settings | None = None,
) -> Collection:
    """Create `NgocNganKnowledge` if missing and return the collection handle."""
    cfg = settings or get_settings()
    weaviate_client = client or get_weaviate_client(cfg)

    if weaviate_client.collections.exists(COLLECTION_NAME):
        return weaviate_client.collections.get(COLLECTION_NAME)

    properties = [
        Property(name="source_id", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="source_type", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="chunk_id", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="locale", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="plant_id", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="name", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="name_vi", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="title", data_type=DataType.TEXT),
        Property(name="slug", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="content", data_type=DataType.TEXT),
    ]

    try:
        weaviate_client.collections.create(
            name=COLLECTION_NAME,
            description=(
                "Bilingual knowledge chunks for Ngoc Ngan garden RAG. "
                "PostgreSQL is the source of truth; price/stock are not stored here."
            ),
            vector_config=_vector_config(cfg),
            properties=properties,
        )
    except UnexpectedStatusCodeError as exc:
        # Race: another worker created the collection.
        if not weaviate_client.collections.exists(COLLECTION_NAME):
            raise
        logger.info("Collection %s already exists (%s)", COLLECTION_NAME, exc)

    return weaviate_client.collections.get(COLLECTION_NAME)


def upsert_knowledge_objects(
    objects: list[dict[str, Any]],
    *,
    client: weaviate.WeaviateClient | None = None,
    settings: Settings | None = None,
) -> int:
    """Insert or replace knowledge objects by stable UUID. Returns upsert count."""
    if not objects:
        return 0

    cfg = settings or get_settings()
    weaviate_client = client or get_weaviate_client(cfg)
    collection = ensure_knowledge_collection(weaviate_client, cfg)

    data_objects = [
        DataObject(
            properties={
                "source_id": str(obj["source_id"]),
                "source_type": str(obj["source_type"]),
                "chunk_id": str(obj["chunk_id"]),
                "locale": str(obj["locale"]),
                "plant_id": str(obj.get("plant_id") or ""),
                "name": obj.get("name") or "",
                "name_vi": obj.get("name_vi") or "",
                "title": obj.get("title") or "",
                "slug": obj.get("slug") or "",
                "content": obj["content"],
            },
            uuid=obj["uuid"],
        )
        for obj in objects
        if obj.get("content")
    ]
    if not data_objects:
        return 0

    result = collection.data.insert_many(data_objects)
    if result.has_errors:
        for index, error in result.errors.items():
            logger.error("Weaviate upsert failed for index %s: %s", index, error)
        raise RuntimeError(f"Weaviate upsert failed for {len(result.errors)} object(s)")
    return len(data_objects)


def delete_knowledge_by_source(
    *,
    source_type: KnowledgeSourceType | str,
    source_id: uuid.UUID | str,
    client: weaviate.WeaviateClient | None = None,
    settings: Settings | None = None,
) -> None:
    """Delete all knowledge objects for a PostgreSQL source record."""
    from weaviate.classes.query import Filter

    cfg = settings or get_settings()
    weaviate_client = client or get_weaviate_client(cfg)
    if not weaviate_client.collections.exists(COLLECTION_NAME):
        return

    collection = weaviate_client.collections.get(COLLECTION_NAME)
    collection.data.delete_many(
        where=Filter.by_property("source_type").equal(str(source_type))
        & Filter.by_property("source_id").equal(str(source_id))
    )


def parse_weaviate_url(url: str) -> tuple[str, int, bool]:
    """Helper for scripts that pass a full URL instead of host/port settings."""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    secure = parsed.scheme == "https"
    return host, port, secure
