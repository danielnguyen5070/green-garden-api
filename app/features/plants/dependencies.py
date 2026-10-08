"""Plant lookups shared by the public storefront routes."""

from __future__ import annotations

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_slug
from app.features.plants.models import Plant
from app.features.plants.service import get_plant_by_slug

PLANT_NOT_FOUND_RESPONSES = {
    status.HTTP_404_NOT_FOUND: {"description": "Plant not found or inactive"}
}


async def get_active_plant_or_404(db: AsyncSession, slug: str) -> Plant:
    """Raises `PlantNotFoundError` (404) for unknown or inactive plants."""
    return await get_plant_by_slug(db, normalize_slug(slug), active_only=True)
