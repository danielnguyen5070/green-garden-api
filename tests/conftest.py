"""Pytest configuration and shared fixtures."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@pytest.fixture(scope="session")
def database_url() -> str:
    return get_settings().database_url


@pytest_asyncio.fixture
async def db_session(database_url: str) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        try:
            yield session
            await session.rollback()
        finally:
            await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(database_url: str) -> AsyncGenerator[None, None]:
    """Verify the database accepts connections."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await engine.dispose()
    yield
