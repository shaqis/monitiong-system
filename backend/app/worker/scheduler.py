import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import Monitor
from app.worker.checker import (
    CheckAlreadyRunning,
    CheckRunner,
    MonitorChanged,
    MonitorNotFound,
    MonitorPaused,
)

logger = logging.getLogger(__name__)

MIN_SLEEP_SECONDS = 1.0


def _interval_seconds(value: int) -> ColumnElement[object]:
    return func.make_interval(0, 0, 0, 0, 0, 0, value)


class Scheduler:
    """Poll due monitors and run their checks without blocking the loop.

    Single-process only: the scheduler and the per-monitor locks in
    ``CheckRunner`` are process-local. Running a second backend replica would
    probe every monitor twice, so compose runs one backend process.
    """

    def __init__(
        self,
        runner: CheckRunner,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._runner = runner
        self._session_factory = session_factory
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="monitor-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def run_once(self) -> int:
        monitor_ids = await self._due_monitor_ids()
        if not monitor_ids:
            return 0

        results = await asyncio.gather(
            *(self._run_check(monitor_id) for monitor_id in monitor_ids),
            return_exceptions=True,
        )
        return sum(1 for result in results if result is True)

    async def _run_check(self, monitor_id: UUID) -> bool:
        try:
            await self._runner.run(monitor_id)
        except (CheckAlreadyRunning, MonitorChanged, MonitorNotFound, MonitorPaused):
            return False
        except Exception:
            logger.exception("Monitor check failed", extra={"monitor_id": str(monitor_id)})
            return False
        return True

    def _due_condition(self, now: datetime) -> ColumnElement[bool]:
        return and_(
            Monitor.is_active.is_(True),
            or_(
                Monitor.last_checked_at.is_(None),
                Monitor.last_checked_at + _interval_seconds(Monitor.interval_seconds) <= now,
                and_(
                    Monitor.consecutive_failures == 1,
                    Monitor.last_checked_at
                    + _interval_seconds(self._settings.scheduler_retry_seconds)
                    <= now,
                ),
            ),
        )

    async def _due_monitor_ids(self) -> list[UUID]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            result = await session.scalars(
                select(Monitor.id)
                .where(self._due_condition(now))
                .order_by(Monitor.last_checked_at.asc().nulls_first())
            )
            return list(result.all())

    async def _next_delay(self) -> float:
        poll_seconds = float(self._settings.scheduler_poll_seconds)
        retry_seconds = self._settings.scheduler_retry_seconds
        async with self._session_factory() as session:
            earliest_retry = await session.scalar(
                select(
                    func.min(
                        Monitor.last_checked_at + _interval_seconds(retry_seconds),
                    )
                ).where(
                    Monitor.is_active.is_(True),
                    Monitor.consecutive_failures == 1,
                )
            )

        if earliest_retry is None:
            return poll_seconds

        seconds_until_retry = (earliest_retry - datetime.now(UTC)).total_seconds()
        return min(poll_seconds, max(seconds_until_retry, MIN_SLEEP_SECONDS))

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Scheduler tick failed")

            if self._stop_event.is_set():
                break

            try:
                delay = await self._next_delay()
            except Exception:
                logger.exception("Scheduler could not compute the next delay")
                delay = float(self._settings.scheduler_poll_seconds)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                continue
            break
