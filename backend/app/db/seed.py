from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_password
from app.db.models import User

SEED_LOCK_NAME = "seed_first_admin"


async def seed_first_admin(session: AsyncSession, settings: Settings) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": SEED_LOCK_NAME},
    )

    user_count = await session.scalar(select(func.count()).select_from(User))
    if user_count:
        return

    session.add(
        User(
            email=str(settings.first_admin_email).strip().lower(),
            full_name=settings.first_admin_name,
            hashed_password=hash_password(settings.first_admin_password),
            role="admin",
            is_active=True,
        )
    )
    await session.commit()
