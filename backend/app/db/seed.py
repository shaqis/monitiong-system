from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_password
from app.db.models import User


async def seed_first_admin(session: AsyncSession, settings: Settings) -> None:
    user_count = await session.scalar(select(func.count()).select_from(User))
    if user_count:
        return

    session.add(
        User(
            email=settings.first_admin_email.strip().lower(),
            full_name=settings.first_admin_name,
            hashed_password=hash_password(settings.first_admin_password),
            role="admin",
            is_active=True,
        )
    )
    await session.commit()
