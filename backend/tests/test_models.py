from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import Incident, Monitor, MonitorCheck, User


async def test_email_uniqueness_is_case_insensitive(session: AsyncSession) -> None:
    session.add(
        User(
            email="admin@example.com",
            full_name="Admin",
            hashed_password=hash_password("password123"),
            role="admin",
        )
    )
    await session.commit()

    session.add(
        User(
            email="ADMIN@EXAMPLE.COM",
            full_name="Admin Two",
            hashed_password=hash_password("password123"),
            role="viewer",
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_role_check_constraint_rejects_unknown_role(
    session: AsyncSession,
) -> None:
    session.add(
        User(
            email="owner@example.com",
            full_name="Owner",
            hashed_password=hash_password("password123"),
            role="owner",
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_monitor_check_constraint_rejects_bad_interval(
    session: AsyncSession,
) -> None:
    session.add(
        Monitor(
            name="Bad Interval",
            url="https://example.com",
            interval_seconds=42,
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_deleting_user_sets_monitor_created_by_null(
    session: AsyncSession,
) -> None:
    user = User(
        email="owner@example.com",
        full_name="Owner",
        hashed_password=hash_password("password123"),
        role="admin",
    )
    session.add(user)
    await session.commit()

    monitor = Monitor(
        name="Example",
        url="https://example.com",
        created_by=user.id,
    )
    session.add(monitor)
    await session.commit()

    await session.delete(user)
    await session.commit()
    await session.refresh(monitor)

    assert monitor.created_by is None


async def test_deleting_monitor_cascades_checks_and_incidents(
    session: AsyncSession,
) -> None:
    monitor = Monitor(name="Example", url="https://example.com")
    session.add(monitor)
    await session.commit()

    session.add_all(
        [
            MonitorCheck(monitor_id=monitor.id, status="UP"),
            Incident(
                monitor_id=monitor.id,
                started_at=datetime.now(UTC),
                cause="Connection timeout",
            ),
        ]
    )
    await session.commit()

    await session.delete(monitor)
    await session.commit()

    checks = (await session.scalars(select(MonitorCheck))).all()
    incidents = (await session.scalars(select(Incident))).all()

    assert checks == []
    assert incidents == []
