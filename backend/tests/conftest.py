import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base

TEST_SCHEMA = "test_phase1"


@pytest.fixture
async def test_engine():
    url = get_settings().database_url
    admin_engine = create_async_engine(url)

    async with admin_engine.begin() as connection:
        await connection.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        await connection.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))

    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": TEST_SCHEMA}},
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    async with admin_engine.begin() as connection:
        await connection.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    await admin_engine.dispose()


@pytest.fixture
async def session(test_engine) -> AsyncSession:
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        yield session
