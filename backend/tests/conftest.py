from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.models import Base, User
from app.db.session import get_db
from app.main import app

TEST_SCHEMA = "test_uptime"


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


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://uptime:uptime@db:5432/uptime",
        first_admin_email="admin@example.com",
        first_admin_password="secret",
        first_admin_name="Test Admin",
        jwt_secret="test-secret-that-is-at-least-32-bytes-long",
    )


@pytest.fixture
async def client(test_engine, test_settings) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: test_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def db_session(test_engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        yield session


@pytest.fixture
async def create_user(test_engine) -> Callable[..., Awaitable[User]]:
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _create(
        email: str = "user@example.com",
        password: str = "password123",
        role: str = "viewer",
        is_active: bool = True,
    ) -> User:
        async with maker() as session:
            user = User(
                email=email.strip().lower(),
                full_name="Test User",
                hashed_password=hash_password(password),
                role=role,
                is_active=is_active,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _create


@pytest.fixture
async def login(client: AsyncClient) -> Callable[..., Awaitable[str]]:
    async def _login(email: str, password: str) -> str:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    return _login
