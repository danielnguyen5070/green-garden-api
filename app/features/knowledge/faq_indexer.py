"""Index / update / delete FAQ knowledge in Weaviate.

FAQ copy is owned by the storefront (`green-garden` messages). It is exported
to `app/data/faqs.json` with `npm run export:faq`, and this module indexes that
snapshot. Any object with `id`, `slug`, `question`/`answer` and optional `_vi`
fields can also be passed directly.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.features.knowledge.builder import (
    bilingual_chunks,
    build_faq_knowledge_text,
    faq_title,
)
from app.features.knowledge.weaviate import (
    KnowledgeSourceType,
    delete_knowledge_by_source,
    delete_knowledge_by_source_type,
    ensure_knowledge_collection,
    get_weaviate_client,
    upsert_knowledge_objects,
)

logger = logging.getLogger(__name__)

FAQ_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "faqs.json"


def load_faq_snapshot(path: Path | None = None) -> list[SimpleNamespace] | None:
    """Load exported storefront FAQs. Returns None when the snapshot is missing."""
    snapshot = path or FAQ_SNAPSHOT_PATH
    if not snapshot.is_file():
        return None

    data = json.loads(snapshot.read_text(encoding="utf-8"))
    faqs: list[SimpleNamespace] = []
    for item in data.get("items", []):
        faq_id = str(item.get("id") or "").strip()
        if not faq_id:
            continue
        faqs.append(SimpleNamespace(**{**item, "id": faq_id, "slug": faq_id}))
    return faqs


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
    """Re-index FAQ knowledge after the source copy changes."""
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
    session: AsyncSession | None = None,
    *,
    settings: Settings | None = None,
    faqs: Sequence[Any] | None = None,
) -> int:
    """Replace all FAQ knowledge with `faqs` or the exported snapshot.

    Existing FAQ objects are wiped first so removed or renamed questions do not
    linger. A missing snapshot leaves the index untouched.
    """
    cfg = settings or get_settings()
    if not cfg.weaviate_enabled:
        logger.warning("Weaviate disabled; skipping FAQ reindex")
        return 0

    rows = list(faqs) if faqs is not None else load_faq_snapshot()
    if rows is None:
        logger.warning(
            "FAQ snapshot not found at %s; run `npm run export:faq` in green-garden",
            FAQ_SNAPSHOT_PATH,
        )
        return 0

    chunks = [
        chunk
        for faq in rows
        if getattr(faq, "is_active", True) is not False
        for chunk in _faq_chunks(faq)
    ]

    client = get_weaviate_client(cfg)
    ensure_knowledge_collection(client, cfg)
    delete_knowledge_by_source_type(
        source_type=KnowledgeSourceType.FAQ,
        client=client,
        settings=cfg,
    )
    return upsert_knowledge_objects(chunks, client=client, settings=cfg)
