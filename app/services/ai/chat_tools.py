"""Chat tools for DeepSeek Function Calling (PostgreSQL + Weaviate)."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import escape_ilike_pattern, normalize_search_query, normalize_slug
from app.models.plant import Plant
from app.services.ai.knowledge.retriever import search_plant_knowledge

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]

# OpenAI / DeepSeek tool schemas — DeepSeek decides when to call these.
CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_plant_price",
            "description": (
                "Get the current selling price of a plant from the live catalogue "
                "(PostgreSQL). Use for price, cost, or 'giá bao nhiêu' questions. "
                "Never invent or guess prices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plant_query": {
                        "type": "string",
                        "description": (
                            "Plant name (EN or VI) or slug, e.g. "
                            "'Cây Chùm Ngây' or 'moringa-tree'."
                        ),
                    },
                },
                "required": ["plant_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": (
                "Check current stock / availability of a plant from the live "
                "catalogue (PostgreSQL). Use for stock, 'còn hàng', availability. "
                "Never invent or guess stock."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plant_query": {
                        "type": "string",
                        "description": (
                            "Plant name (EN or VI) or slug, e.g. "
                            "'Cây Chùm Ngây' or 'moringa-tree'."
                        ),
                    },
                },
                "required": ["plant_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_plant_knowledge",
            "description": (
                "Search plant care and descriptive knowledge (light, watering, "
                "soil, characteristics, growing tips). Do NOT use for current "
                "price or stock — those require get_plant_price / check_stock."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural-language knowledge query, including the plant "
                            "name when known, e.g. 'Cây Chùm Ngây ánh sáng'."
                        ),
                    },
                    "locale": {
                        "type": "string",
                        "enum": ["vi", "en"],
                        "description": "Preferred knowledge locale when known.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


async def _find_active_plant(
    session: AsyncSession, plant_query: str
) -> Plant | None:
    """Resolve an active plant by slug or partial EN/VI name."""
    cleaned = normalize_search_query(plant_query)
    if not cleaned:
        return None

    slug = normalize_slug(cleaned)
    if slug:
        result = await session.execute(
            select(Plant).where(Plant.is_active.is_(True), Plant.slug == slug).limit(1)
        )
        plant = result.scalar_one_or_none()
        if plant is not None:
            return plant

    pattern = f"%{escape_ilike_pattern(cleaned)}%"
    result = await session.execute(
        select(Plant)
        .where(
            Plant.is_active.is_(True),
            or_(
                Plant.name.ilike(pattern, escape="\\"),
                Plant.name_vi.ilike(pattern, escape="\\"),
                Plant.slug.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(Plant.name)
        .limit(5)
    )
    matches = list(result.scalars().all())
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Prefer exact (case-insensitive) name / name_vi when several ILIKE hits.
    lowered = cleaned.casefold()
    for plant in matches:
        if (plant.name or "").casefold() == lowered:
            return plant
        if (plant.name_vi or "").casefold() == lowered:
            return plant
    return matches[0]


def _plant_identity(plant: Plant) -> dict[str, Any]:
    return {
        "plant_id": str(plant.id),
        "name": plant.name,
        "name_vi": plant.name_vi,
        "slug": plant.slug,
    }


async def get_plant_price(
    session: AsyncSession, *, plant_query: str
) -> dict[str, Any]:
    """Return live catalogue prices from PostgreSQL."""
    plant = await _find_active_plant(session, plant_query)
    if plant is None:
        return {
            "found": False,
            "plant_query": plant_query,
            "error": "Plant not found in the catalogue",
        }
    return {
        "found": True,
        **_plant_identity(plant),
        "price": str(plant.price),
        "price_vi": str(plant.price_vi) if plant.price_vi is not None else None,
        "currency": "VND",
    }


async def check_stock(
    session: AsyncSession, *, plant_query: str
) -> dict[str, Any]:
    """Return live stock from PostgreSQL."""
    plant = await _find_active_plant(session, plant_query)
    if plant is None:
        return {
            "found": False,
            "plant_query": plant_query,
            "error": "Plant not found in the catalogue",
        }
    stock = int(plant.stock)
    return {
        "found": True,
        **_plant_identity(plant),
        "stock": stock,
        "in_stock": stock > 0,
        "is_active": bool(plant.is_active),
    }


async def search_plant_knowledge_tool(
    *,
    query: str,
    locale: str | None = None,
) -> dict[str, Any]:
    """Wrap Weaviate retrieval for Function Calling."""
    return search_plant_knowledge(query, locale=locale)


async def execute_chat_tool(
    name: str,
    arguments_json: str,
    *,
    session: AsyncSession,
) -> dict[str, Any]:
    """Dispatch a DeepSeek tool call. Never raises — returns an error payload."""
    try:
        raw_args = json.loads(arguments_json or "{}")
        if not isinstance(raw_args, dict):
            return {"ok": False, "error": "Invalid tool arguments"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "Invalid tool arguments JSON"}

    try:
        if name == "get_plant_price":
            return await get_plant_price(
                session, plant_query=str(raw_args.get("plant_query") or "")
            )
        if name == "check_stock":
            return await check_stock(
                session, plant_query=str(raw_args.get("plant_query") or "")
            )
        if name == "search_plant_knowledge":
            locale = raw_args.get("locale")
            return await search_plant_knowledge_tool(
                query=str(raw_args.get("query") or ""),
                locale=str(locale) if locale else None,
            )
        return {"ok": False, "error": f"Unknown tool: {name}"}
    except Exception:  # noqa: BLE001
        logger.exception("Chat tool failed name=%s", name)
        return {"ok": False, "error": f"Tool '{name}' failed"}
