from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path

import pytest
from sqlalchemy import select, text
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


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "d7e1f2a3b4c5_harden_incident_invariants.py"
)
DEDUPE_OPEN_INCIDENTS = run_path(str(MIGRATION_PATH))["DEDUPE_OPEN_INCIDENTS"]


async def test_incident_dedupe_keeps_the_earliest_open_incident(
    session_factory,
    create_monitor,
) -> None:
    monitor = await create_monitor()
    now = datetime.now(UTC).replace(microsecond=0)

    async with session_factory() as setup:
        await setup.execute(text("DROP INDEX IF EXISTS uq_incidents_open_monitor"))
        setup.add_all(
            [
                Incident(
                    monitor_id=monitor.id,
                    started_at=now - timedelta(hours=hours),
                    cause=f"{hours}h ago",
                )
                for hours in (3, 1, 2)
            ]
        )
        await setup.commit()

    async with session_factory() as dedupe:
        await dedupe.execute(text(DEDUPE_OPEN_INCIDENTS))
        await dedupe.execute(
            text(
                "CREATE UNIQUE INDEX uq_incidents_open_monitor "
                "ON incidents (monitor_id) WHERE resolved_at IS NULL"
            )
        )
        await dedupe.commit()

    async with session_factory() as check:
        rows = list(
            (
                await check.scalars(
                    select(Incident)
                    .where(Incident.monitor_id == monitor.id)
                    .order_by(Incident.started_at)
                )
            ).all()
        )

    assert [row.resolved_at is None for row in rows] == [True, False, False]
    assert rows[0].started_at == now - timedelta(hours=3)
