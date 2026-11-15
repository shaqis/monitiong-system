import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import DatabaseSettings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APPLIED_REVISION = "d7e1f2a3b4c5"
LEGACY_REVISION = "c4d2e6f8a1b3"
_ALEMBIC_CONFIG = Config()
_ALEMBIC_CONFIG.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
HEAD_REVISION = ScriptDirectory.from_config(_ALEMBIC_CONFIG).get_current_head()
assert HEAD_REVISION is not None

MONITOR_ID = "00000000-0000-0000-0000-000000000001"
CHECK_INDEX = "ix_monitor_checks_monitor_id_checked_at"
CHECK_INDEX_BUILD = f"{CHECK_INDEX}_build"
EARLIEST_OPEN_INCIDENT = datetime(2026, 1, 1, tzinfo=UTC)

APPLIED_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX uq_incidents_open_monitor "
    "ON incidents (monitor_id) WHERE resolved_at IS NULL"
)
APPLIED_CHECK_INDEX = (
    f"CREATE INDEX {CHECK_INDEX} ON monitor_checks (monitor_id, checked_at DESC) INCLUDE (status)"
)


@dataclass
class ScratchDatabase:
    name: str
    url: str
    engine: AsyncEngine

    async def run(self, *args: str) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            *args,
            cwd=BACKEND_ROOT,
            env={**os.environ, "DATABASE_URL": self.url},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        except (TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise
        return int(process.returncode or 0), stdout.decode(), stderr.decode()

    async def current(self) -> str:
        async with self.engine.connect() as connection:
            value = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert value is not None
        return str(value)


@pytest.fixture
async def scratch_database() -> AsyncIterator[ScratchDatabase]:
    base = make_url(DatabaseSettings().database_url)
    name = f"test_migration_{uuid4().hex[:12]}"
    admin_engine = create_async_engine(
        base.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))

    url = base.set(database=name).render_as_string(hide_password=False)
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        yield ScratchDatabase(name=name, url=url, engine=engine)
    finally:
        await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin_engine.dispose()


async def _apply_applied_revision(db: ScratchDatabase) -> None:
    """Reproduce the state #18 left: indexes present, revision recorded."""
    code, _, stderr = await db.run("upgrade", LEGACY_REVISION)
    assert code == 0, stderr

    async with db.engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO monitors (id, name, url) "
                "VALUES (:id, 'Migration', 'https://example.com')"
            ),
            {"id": MONITOR_ID},
        )
        await connection.execute(
            text(
                "INSERT INTO incidents (monitor_id, started_at, cause) "
                "VALUES (:id, '2026-01-03 00:00:00+00', 'newest')"
            ),
            {"id": MONITOR_ID},
        )
        await connection.execute(text(APPLIED_UNIQUE_INDEX))
        await connection.execute(text(f"DROP INDEX {CHECK_INDEX}"))
        await connection.execute(text(APPLIED_CHECK_INDEX))

    code, _, stderr = await db.run("stamp", APPLIED_REVISION)
    assert code == 0, stderr


async def _reopen_duplicates(db: ScratchDatabase) -> None:
    """The repair must not assume the unique index is still there."""
    async with db.engine.begin() as connection:
        await connection.execute(text("DROP INDEX uq_incidents_open_monitor"))
        await connection.execute(
            text(
                "INSERT INTO incidents (monitor_id, started_at, cause) VALUES "
                "(:id, '2026-01-01 00:00:00+00', 'oldest'), "
                "(:id, '2026-01-02 00:00:00+00', 'middle')"
            ),
            {"id": MONITOR_ID},
        )


async def _open_incident_starts(db: ScratchDatabase) -> list[datetime]:
    async with db.engine.connect() as connection:
        rows = await connection.scalars(
            text("SELECT started_at FROM incidents WHERE resolved_at IS NULL ORDER BY started_at")
        )
        return list(rows)


async def _check_index_state(db: ScratchDatabase) -> dict[str, object]:
    async with db.engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT c.relfilenode, i.indisvalid, pg_get_indexdef(i.indexrelid) "
                    "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                    "WHERE c.relname = :name"
                ),
                {"name": CHECK_INDEX},
            )
        ).one()
    return {"relfilenode": row[0], "valid": row[1], "definition": row[2]}


async def _index_exists(db: ScratchDatabase, name: str) -> bool:
    async with db.engine.connect() as connection:
        return bool(
            await connection.scalar(
                text("SELECT count(*) FROM pg_class WHERE relname = :name AND relkind = 'i'"),
                {"name": name},
            )
        )


async def _index_is_valid(db: ScratchDatabase, name: str) -> bool | None:
    async with db.engine.connect() as connection:
        return await connection.scalar(
            text(
                "SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE c.relname = :name"
            ),
            {"name": name},
        )


async def _incidents_share_lock_held(db: ScratchDatabase) -> bool:
    async with db.engine.connect() as connection:
        count = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                "WHERE c.relname = 'incidents' AND l.mode = 'ShareLock' AND l.granted"
            )
        )
    return bool(count)


async def test_applied_revision_upgrade_keeps_the_earliest_open_incident(
    scratch_database: ScratchDatabase,
) -> None:
    db = scratch_database
    await _apply_applied_revision(db)
    await _reopen_duplicates(db)
    before = await _check_index_state(db)
    assert before["valid"] is True

    code, _, stderr = await db.run("upgrade", "head")
    assert code == 0, stderr

    assert await db.current() == HEAD_REVISION
    assert await _open_incident_starts(db) == [EARLIEST_OPEN_INCIDENT]

    after = await _check_index_state(db)
    assert after["valid"] is True
    assert after["relfilenode"] != before["relfilenode"]
    assert "INCLUDE (status)" in str(after["definition"])
    assert await _index_exists(db, "uq_incidents_open_monitor")


async def test_interrupted_check_index_build_keeps_the_previous_index_and_retries(
    scratch_database: ScratchDatabase,
) -> None:
    db = scratch_database
    await _apply_applied_revision(db)
    before = await _check_index_state(db)

    async with db.engine.connect() as connection:
        await connection.execute(text(f"ALTER DATABASE \"{db.name}\" SET lock_timeout = '500ms'"))

    async with db.engine.connect() as writer:
        await writer.execute(text("BEGIN"))
        await writer.execute(
            text("INSERT INTO monitor_checks (monitor_id, status) VALUES (:id, 'UP')"),
            {"id": MONITOR_ID},
        )

        # The open write makes the concurrent build wait for its snapshot, so
        # the database lock_timeout turns the build into a real failure.
        code, _, stderr = await db.run("upgrade", "head")
        assert code != 0
        assert "lock timeout" in stderr.lower()

        failed = await _check_index_state(db)
        assert failed["valid"] is True
        assert failed["relfilenode"] == before["relfilenode"]
        assert await _index_is_valid(db, CHECK_INDEX_BUILD) is False
        assert await db.current() == APPLIED_REVISION
        assert await _index_exists(db, "uq_incidents_open_monitor")

        await writer.execute(text("ROLLBACK"))

    code, _, stderr = await db.run("upgrade", "head")
    assert code == 0, stderr

    assert await db.current() == HEAD_REVISION
    retried = await _check_index_state(db)
    assert retried["valid"] is True
    assert retried["relfilenode"] != before["relfilenode"]
    assert await _index_is_valid(db, CHECK_INDEX_BUILD) is None


async def test_share_lock_blocks_an_incident_insert_during_the_dedupe(
    scratch_database: ScratchDatabase,
) -> None:
    db = scratch_database
    await _apply_applied_revision(db)
    await _reopen_duplicates(db)

    async with db.engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE FUNCTION slow_incident_dedupe() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ "
                "BEGIN PERFORM pg_sleep(0.5); RETURN NEW; END; $$"
            )
        )
        await connection.execute(
            text(
                "CREATE TRIGGER slow_incident_dedupe BEFORE UPDATE ON incidents "
                "FOR EACH ROW EXECUTE FUNCTION slow_incident_dedupe()"
            )
        )

    upgrade = asyncio.create_task(db.run("upgrade", "head"))
    try:
        deadline = asyncio.get_running_loop().time() + 30
        while not await _incidents_share_lock_held(db):
            if upgrade.done():
                code, _, stderr = upgrade.result()
                raise AssertionError(f"upgrade exited early with {code}: {stderr}")
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("incidents share lock was never observed")
            await asyncio.sleep(0.02)

        with pytest.raises(DBAPIError) as failure:
            async with db.engine.connect() as connection:
                await connection.execute(text("BEGIN"))
                try:
                    await connection.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    await connection.execute(
                        text(
                            "INSERT INTO incidents (monitor_id, started_at, cause) "
                            "VALUES (:id, now(), 'raced')"
                        ),
                        {"id": MONITOR_ID},
                    )
                finally:
                    await connection.execute(text("ROLLBACK"))
        assert "lock timeout" in str(failure.value).lower()

        code, _, stderr = await asyncio.wait_for(upgrade, timeout=60)
    finally:
        if not upgrade.done():
            upgrade.cancel()
            with suppress(asyncio.CancelledError):
                await upgrade

    assert code == 0, stderr
    assert await _open_incident_starts(db) == [EARLIEST_OPEN_INCIDENT]
