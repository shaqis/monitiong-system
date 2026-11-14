from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import verify_password
from app.db.models import User
from app.db.seed import seed_first_admin


def build_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://uptime:uptime@db:5432/uptime",
        first_admin_email="admin@example.com",
        first_admin_password="secret",
        first_admin_name="Test Admin",
        jwt_secret="test-secret-that-is-at-least-32-bytes-long",
    )


async def test_seed_creates_first_admin(session: AsyncSession) -> None:
    await seed_first_admin(session, build_settings())

    users = (await session.scalars(select(User))).all()

    assert len(users) == 1
    assert users[0].email == "admin@example.com"
    assert users[0].role == "admin"
    assert users[0].is_active is True
    assert verify_password("secret", users[0].hashed_password)


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    settings = build_settings()

    await seed_first_admin(session, settings)
    await seed_first_admin(session, settings)

    count = await session.scalar(select(func.count()).select_from(User))
    assert count == 1


async def test_seed_skips_when_users_exist(session: AsyncSession) -> None:
    session.add(
        User(
            email="viewer@example.com",
            full_name="Viewer",
            hashed_password="not-used",
            role="viewer",
            is_active=True,
        )
    )
    await session.commit()

    await seed_first_admin(session, build_settings())

    users = (await session.scalars(select(User))).all()

    assert len(users) == 1
    assert users[0].email == "viewer@example.com"
