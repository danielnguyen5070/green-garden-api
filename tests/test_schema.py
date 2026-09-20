"""Verify migrated schema exposes the expected core tables."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


EXPECTED_TABLES = {
    "admins",
    "categories",
    "plants",
    "plant_images",
    "plant_pot_sizes",
    "customers",
    "orders",
    "order_items",
    "reviews",
    "notifications",
}


@pytest.mark.asyncio
async def test_core_tables_exist_after_migration(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            """
        )
    )
    tables = {row[0] for row in result.fetchall()}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables after migration: {sorted(missing)}"
