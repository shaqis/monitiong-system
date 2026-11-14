import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Incident, Monitor, MonitorCheck
from app.worker.prober import (
    DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    ProbeResult,
    ProbeTarget,
    probe,
)
from app.worker.state import MonitorState, apply_probe_result

Prober = Callable[..., Awaitable[ProbeResult]]


class MonitorNotFound(Exception):
    """The monitor does not exist."""


class MonitorPaused(Exception):
    """The monitor is paused and must not be checked."""


class CheckAlreadyRunning(Exception):
    """A check for this monitor is already in flight."""


class CheckRunner:
    """Run one probe and persist its check plus monitor transition.

    One in-process lock per monitor spans the probe and the write. The probe
    never holds a database connection, and the write is a single short
    transaction with a row lock.
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
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._user_agent = user_agent
        self._ssl_inspect_timeout_seconds = ssl_inspect_timeout_seconds

    def _lock_for(self, monitor_id: UUID) -> asyncio.Lock:
        lock = self._locks.get(monitor_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[monitor_id] = lock
        return lock

    async def run(self, monitor_id: UUID, *, require_active: bool = True) -> MonitorCheck:
        lock = self._lock_for(monitor_id)
        if lock.locked():
            raise CheckAlreadyRunning(str(monitor_id))

        async with lock:
            target = await self._load_target(monitor_id, require_active=require_active)
            async with self._semaphore:
                result = await self._prober(
                    target,
                    user_agent=self._user_agent,
                    ssl_inspect_timeout_seconds=self._ssl_inspect_timeout_seconds,
                )
            return await self._record(monitor_id, result, require_active=require_active)

    async def _load_target(self, monitor_id: UUID, *, require_active: bool) -> ProbeTarget:
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
        if require_active and not row.is_active:
            raise MonitorPaused(str(monitor_id))

        return ProbeTarget(
            url=row.url,
            http_method=row.http_method,
            timeout_seconds=row.timeout_seconds,
            expected_status_code=row.expected_status_code,
            keyword=row.keyword,
            check_ssl=row.check_ssl,
        )

    async def _record(
        self,
        monitor_id: UUID,
        result: ProbeResult,
        *,
        require_active: bool,
    ) -> MonitorCheck:
        checked_at = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                monitor = await session.scalar(
                    select(Monitor).where(Monitor.id == monitor_id).with_for_update()
                )
                if monitor is None:
                    raise MonitorNotFound(str(monitor_id))
                if require_active and not monitor.is_active:
                    raise MonitorPaused(str(monitor_id))

                open_incident = await session.scalar(
                    select(Incident)
                    .where(
                        Incident.monitor_id == monitor_id,
                        Incident.resolved_at.is_(None),
                    )
                    .order_by(Incident.started_at.desc())
                    .limit(1)
                )

                transition = apply_probe_result(
                    MonitorState(
                        current_status=monitor.current_status,
                        consecutive_failures=monitor.consecutive_failures,
                        has_open_incident=open_incident is not None,
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
                    session.add(
                        Incident(
                            monitor_id=monitor_id,
                            started_at=checked_at,
                            cause=result.error_message or "Check failed",
                        )
                    )
                elif transition.resolve_incident and open_incident is not None:
                    open_incident.resolved_at = checked_at

            await session.refresh(check)

        return check
