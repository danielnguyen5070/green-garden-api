"""Re-index all PostgreSQL knowledge sources into Weaviate.

Usage:
    python -m scripts.reindex_knowledge
    python -m scripts.reindex_knowledge --include-inactive
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services.ai.knowledge.blog_indexer import reindex_all_blogs
from app.services.ai.knowledge.faq_indexer import reindex_all_faqs
from app.services.ai.knowledge.plant_indexer import reindex_all_plants
from app.services.ai.knowledge.weaviate import (
    close_weaviate_client,
    ensure_knowledge_collection,
    get_weaviate_client,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("scripts.reindex_knowledge")


async def _run(*, active_only: bool) -> int:
    settings = get_settings()
    if not settings.weaviate_enabled:
        logger.error(
            "WEAVIATE_ENABLED is false. Set WEAVIATE_ENABLED=true and ensure "
            "Weaviate is reachable, then retry."
        )
        return 1

    client = get_weaviate_client(settings)
    ensure_knowledge_collection(client, settings)
    logger.info("NgocNganKnowledge collection ready")

    async with AsyncSessionLocal() as session:
        plants = await reindex_all_plants(
            session, settings=settings, active_only=active_only
        )
        faqs = await reindex_all_faqs(session, settings=settings)
        blogs = await reindex_all_blogs(session, settings=settings)

    logger.info(
        "Reindex complete: plants_objects=%s faq_objects=%s blog_objects=%s",
        plants,
        faqs,
        blogs,
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Re-index plant / FAQ / blog knowledge into Weaviate"
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Also index inactive plants (default: active only)",
    )
    args = parser.parse_args(argv)

    try:
        code = asyncio.run(_run(active_only=not args.include_inactive))
    finally:
        close_weaviate_client()
    sys.exit(code)


if __name__ == "__main__":
    main()
