import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Incident, Monitor, MonitorCheck
from app.worker.prober import (
    DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    ProbeResult,
    ProbeTarget,
    create_ssl_executor,
    probe,
)
from app.worker.state import MonitorState, apply_probe_result

Prober = Callable[..., Awaitable[ProbeResult]]

TARGET_FIELDS: tuple[str, ...] = (
    "url",
    "http_method",
    "expected_status_code",
    "keyword",
)


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    """The four fields in TARGET_FIELDS that were probed, used to reject stale results."""

    url: str
    http_method: str
    expected_status_code: int
    keyword: str | None


class MonitorNotFound(Exception):
    """The monitor does not exist."""


class MonitorPaused(Exception):
    """The monitor is paused and must not be checked."""


class CheckAlreadyRunning(Exception):
    """A check for this monitor is already in flight."""


class MonitorChanged(Exception):
    """The monitor target changed while the probe was in flight."""


class CheckRunner:
    """Run one probe and persist its check plus monitor transition.

    One in-process lock per monitor spans the probe and the write. The probe
    never holds a database connection, and the write is a single short
    transaction with a row lock. The admission semaphore is taken before the
    pre-probe read, so a due-monitor fan-out cannot open more sessions than
    the pool allows.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        prober: Prober = probe,
        *,
        max_concurrent_checks: int = 20,
        user_agent: str = DEFAULT_USER_AGENT,
        ssl_inspect_timeout_seconds: float = DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._prober = prober
        self._semaphore = asyncio.Semaphore(max_concurrent_checks)
        self._ssl_executor = create_ssl_executor(max_concurrent_checks)
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._user_agent = user_agent
        self._ssl_inspect_timeout_seconds = ssl_inspect_timeout_seconds

    def _lock_for(self, monitor_id: UUID) -> asyncio.Lock:
        lock = self._locks.get(monitor_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[monitor_id] = lock
        return lock

    def forget(self, monitor_id: UUID) -> None:
        """Drop the per-monitor lock once a deleted monitor cannot be running."""
        lock = self._locks.get(monitor_id)
        if lock is None:
            return
        if not lock.locked():
            self._locks.pop(monitor_id, None)

    def aclose(self) -> None:
        self._ssl_executor.shutdown(wait=False, cancel_futures=True)

    async def run(self, monitor_id: UUID) -> MonitorCheck:
        lock = self._lock_for(monitor_id)
        if lock.locked():
            raise CheckAlreadyRunning(str(monitor_id))

        try:
            async with self._semaphore:
                async with lock:
                    target, snapshot = await self._load_target(monitor_id)
                    result = await self._prober(
                        target,
                        user_agent=self._user_agent,
                        ssl_inspect_timeout_seconds=self._ssl_inspect_timeout_seconds,
                        ssl_executor=self._ssl_executor,
                    )
                    return await self._record(monitor_id, snapshot, result)
        except (MonitorNotFound, MonitorPaused):
            self.forget(monitor_id)
            raise

    async def _load_target(self, monitor_id: UUID) -> tuple[ProbeTarget, TargetSnapshot]:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        Monitor.url,
                        Monitor.http_method,
                        Monitor.timeout_seconds,
                        Monitor.expected_status_code,
                        Monitor.keyword,
                        Monitor.check_ssl,
                        Monitor.is_active,
                    ).where(Monitor.id == monitor_id)
                )
            ).first()

        if row is None:
            raise MonitorNotFound(str(monitor_id))
        if not row.is_active:
            raise MonitorPaused(str(monitor_id))

        target = ProbeTarget(
            url=row.url,
            http_method=row.http_method,
            timeout_seconds=row.timeout_seconds,
            expected_status_code=row.expected_status_code,
            keyword=row.keyword,
            check_ssl=row.check_ssl,
        )
        snapshot = TargetSnapshot(
            url=row.url,
            http_method=row.http_method,
            expected_status_code=row.expected_status_code,
            keyword=row.keyword,
        )
        return target, snapshot

    async def _record(
        self,
        monitor_id: UUID,
        snapshot: TargetSnapshot,
        result: ProbeResult,
    ) -> MonitorCheck:
        checked_at = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                monitor = await session.scalar(
                    select(Monitor).where(Monitor.id == monitor_id).with_for_update()
                )
                if monitor is None:
                    raise MonitorNotFound(str(monitor_id))
                if not monitor.is_active:
                    raise MonitorPaused(str(monitor_id))
                if any(
                    getattr(monitor, field) != getattr(snapshot, field) for field in TARGET_FIELDS
                ):
                    raise MonitorChanged(str(monitor_id))

                open_incident_id = await session.scalar(
                    select(Incident.id)
                    .where(
                        Incident.monitor_id == monitor_id,
                        Incident.resolved_at.is_(None),
                    )
                    .limit(1)
                )

                transition = apply_probe_result(
                    MonitorState(
                        consecutive_failures=monitor.consecutive_failures,
                        has_open_incident=open_incident_id is not None,
                    ),
                    result.ok,
                )

                check = MonitorCheck(
                    monitor_id=monitor_id,
                    status="UP" if result.ok else "DOWN",
                    status_code=result.status_code,
                    response_time_ms=result.response_time_ms,
                    keyword_matched=result.keyword_matched,
                    error_message=result.error_message,
                    checked_at=checked_at,
                )
                session.add(check)

                monitor.current_status = transition.current_status
                monitor.consecutive_failures = transition.consecutive_failures
                monitor.last_checked_at = checked_at
                if result.ssl_days_remaining is not None:
                    monitor.ssl_days_remaining = result.ssl_days_remaining

                if transition.open_incident:
                    # A second replica can insert the open incident between the
                    # read above and this write. Dropping the conflict keeps the
                    # check and the status update in the same transaction.
                    await session.execute(
                        pg_insert(Incident)
                        .values(
                            monitor_id=monitor_id,
                            started_at=checked_at,
                            cause=result.error_message or "Check failed",
                        )
                        .on_conflict_do_nothing(
                            index_elements=["monitor_id"],
                            index_where=Incident.resolved_at.is_(None),
                        )
                    )
                elif transition.resolve_incident:
                    await session.execute(
                        update(Incident)
                        .where(
                            Incident.monitor_id == monitor_id,
                            Incident.resolved_at.is_(None),
                        )
                        .values(resolved_at=checked_at)
                    )

            await session.refresh(check)

        return check
