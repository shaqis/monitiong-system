import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Incident, Monitor, MonitorCheck
from app.notifications.events import IncidentEvent, IncidentOpened, IncidentResolved
from app.notifications.service import IncidentNotifier
from app.worker.prober import (
    DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    ProbeResult,
    ProbeTarget,
    create_ssl_executor,
    probe,
)
from app.worker.state import MonitorState, apply_probe_result

logger = logging.getLogger(__name__)

Prober = Callable[..., Awaitable[ProbeResult]]

TARGET_FIELDS: tuple[str, ...] = (
    "url",
    "http_method",
    "expected_status_code",
    "keyword",
)


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    """Target fields captured before the probe, so a mid-flight edit is rejected."""

    url: str
    http_method: str
    expected_status_code: int
    keyword: str | None


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    check: MonitorCheck
    event: IncidentEvent | None = None


class MonitorNotFound(Exception):
    """The monitor does not exist."""


class MonitorPaused(Exception):
    """The monitor is paused and must not be checked."""


class CheckAlreadyRunning(Exception):
    """A check for this monitor is already in flight or queued in this process."""


class MonitorChanged(Exception):
    """The monitor target changed while the probe was in flight."""


class CheckRunner:
    """Probe once, then write the check and the monitor transition atomically.

    Admission is a synchronous in-flight set taken before the semaphore, so a
    second caller is rejected even while queued, and a due-monitor fan-out
    cannot open more sessions than the pool allows. The guarantee stops at the
    process boundary: a second replica can probe the same monitor, and only
    the partial unique index keeps one open incident.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        prober: Prober = probe,
        *,
        max_concurrent_checks: int = 20,
        user_agent: str = DEFAULT_USER_AGENT,
        ssl_inspect_timeout_seconds: float = DEFAULT_SSL_INSPECT_TIMEOUT_SECONDS,
        notifier: IncidentNotifier | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._prober = prober
        self._semaphore = asyncio.Semaphore(max_concurrent_checks)
        self._ssl_executor = create_ssl_executor(max_concurrent_checks)
        self._inflight: set[UUID] = set()
        self._user_agent = user_agent
        self._ssl_inspect_timeout_seconds = ssl_inspect_timeout_seconds
        self._notifier = notifier

    def aclose(self) -> None:
        self._ssl_executor.shutdown(wait=False, cancel_futures=True)

    async def run(self, monitor_id: UUID) -> MonitorCheck:
        if monitor_id in self._inflight:
            raise CheckAlreadyRunning(str(monitor_id))
        self._inflight.add(monitor_id)
        try:
            async with self._semaphore:
                target, snapshot = await self._load_target(monitor_id)
                result = await self._prober(
                    target,
                    user_agent=self._user_agent,
                    ssl_inspect_timeout_seconds=self._ssl_inspect_timeout_seconds,
                    ssl_executor=self._ssl_executor,
                )
                outcome = await self._record(monitor_id, snapshot, result)
                if outcome.event is not None and self._notifier is not None:
                    try:
                        await self._notifier.notify(outcome.event)
                    except Exception:
                        logger.exception(
                            "Incident notification failed",
                            extra={"monitor_id": str(monitor_id)},
                        )
                return outcome.check
        finally:
            self._inflight.discard(monitor_id)

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
    ) -> RecordOutcome:
        checked_at = datetime.now(UTC)
        event: IncidentEvent | None = None
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

                open_incident = (
                    await session.execute(
                        select(Incident.id, Incident.started_at)
                        .where(
                            Incident.monitor_id == monitor_id,
                            Incident.resolved_at.is_(None),
                        )
                        .limit(1)
                    )
                ).first()

                transition = apply_probe_result(
                    MonitorState(
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
                    # None means "not inspected" (non-HTTPS, check_ssl off, or
                    # probe failure), not "certificate gone", so keep the last
                    # known reading.
                    monitor.ssl_days_remaining = result.ssl_days_remaining

                monitor_name = monitor.name
                monitor_url = monitor.url
                opened = False
                resolved = False

                if transition.open_incident:
                    # A second replica can insert the open incident between the
                    # read above and this write. Dropping the conflict keeps the
                    # check and the status update in the same transaction. Only
                    # the writer that inserts the row notifies, so a conflict
                    # cannot send a duplicate email.
                    inserted = await session.execute(
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
                    opened = inserted.rowcount == 1
                elif transition.resolve_incident:
                    closed = await session.execute(
                        update(Incident)
                        .where(
                            Incident.monitor_id == monitor_id,
                            Incident.resolved_at.is_(None),
                        )
                        .values(resolved_at=checked_at)
                    )
                    resolved = bool(closed.rowcount)

            await session.refresh(check)

            if opened:
                event = IncidentOpened(
                    monitor_id=monitor_id,
                    monitor_name=monitor_name,
                    monitor_url=monitor_url,
                    cause=result.error_message or "Check failed",
                    opened_at=checked_at,
                )
            elif resolved and open_incident is not None:
                event = IncidentResolved(
                    monitor_id=monitor_id,
                    monitor_name=monitor_name,
                    monitor_url=monitor_url,
                    started_at=open_incident.started_at,
                    resolved_at=checked_at,
                    duration_seconds=max(
                        0,
                        int((checked_at - open_incident.started_at).total_seconds()),
                    ),
                )

        return RecordOutcome(check=check, event=event)
