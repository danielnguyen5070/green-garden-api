"""Pytest configuration and shared fixtures.

Auth/API tests use TEST_DATABASE_URL (green_garden_test by default),
not the primary application database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_password, normalize_email
from app.models.admin import Admin
from app.models.category import Category


def _admin_url_for_maintenance(database_url: str) -> str:
    """Connect to the default `postgres` DB to create the test database."""
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/postgres"))


@pytest.fixture(scope="session")
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def database_url(settings) -> str:
    """Primary app DB — used by model/schema tests with rollback."""
    return settings.database_url


@pytest.fixture(scope="session")
def test_database_url(settings) -> str:
    """Dedicated test database for auth/API tests."""
    if settings.test_database_url:
        return settings.test_database_url
    return settings.database_url.replace("/green_garden", "/green_garden_test", 1)


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database(test_database_url: str) -> None:
    """Create green_garden_test if needed and apply migrations once per session."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    async def _ensure_db() -> None:
        parsed = urlparse(test_database_url)
        db_name = parsed.path.lstrip("/")
        maintenance = create_async_engine(
            _admin_url_for_maintenance(test_database_url),
            isolation_level="AUTOCOMMIT",
            pool_pre_ping=True,
        )
        async with maintenance.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if exists.scalar() is None:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        await maintenance.dispose()

    asyncio.run(_ensure_db())

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    get_settings.cache_clear()

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    # Restore primary DATABASE_URL for app settings used by model tests
    if previous_url is not None:
        os.environ["DATABASE_URL"] = previous_url
    get_settings.cache_clear()


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
async def test_db_session(test_database_url: str) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        finally:
            await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(database_url: str) -> AsyncGenerator[None, None]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def client(test_database_url: str) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client against the ASGI app, using the test database."""
    from app.core import database as database_module
    from app.core.config import get_settings
    from app.main import app

    os.environ["DATABASE_URL"] = test_database_url
    get_settings.cache_clear()
    cfg = get_settings()

    engine = create_async_engine(cfg.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    database_module.engine = engine
    database_module.AsyncSessionLocal = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def active_admin(test_db_session: AsyncSession) -> Admin:
    email = normalize_email(f"admin-{uuid4()}@example.com")
    admin = Admin(
        name="Test Admin",
        email=email,
        password_hash=hash_password("correct-password"),
        is_active=True,
    )
    test_db_session.add(admin)
    await test_db_session.commit()
    await test_db_session.refresh(admin)
    return admin


@pytest_asyncio.fixture
async def test_category(test_db_session: AsyncSession) -> Category:
    """Category used as a foreign key target by plant tests."""
    unique = uuid4().hex[:8]
    category = Category(
        name=f"Test Category {unique}",
        slug=f"test-category-{unique}",
        is_active=True,
    )
    test_db_session.add(category)
    await test_db_session.commit()
    await test_db_session.refresh(category)
    return category


@pytest_asyncio.fixture
async def inactive_admin(test_db_session: AsyncSession) -> Admin:
    email = normalize_email(f"inactive-{uuid4()}@example.com")
    admin = Admin(
        name="Inactive Admin",
        email=email,
        password_hash=hash_password("correct-password"),
        is_active=False,
    )
    test_db_session.add(admin)
    await test_db_session.commit()
    await test_db_session.refresh(admin)
    return admin
