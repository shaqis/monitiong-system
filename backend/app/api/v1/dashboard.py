from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.analytics import latency_bucket, to_latency_point
from app.core.deps import get_current_user
from app.db.models import Incident, Monitor, MonitorCheck, User
from app.db.session import get_db
from app.schemas.dashboard import DashboardSummary, IncidentSummary, MonitorStatusStrip
from app.schemas.monitor import RANGE_SECONDS, TimeRange

router = APIRouter()

RECENT_STATUS_COUNT = 20
RECENT_INCIDENT_LIMIT = 20
STATUS_STRIP_LOOKBACK_DAYS = 30


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    time_range: TimeRange = Query(default="24h", alias="range"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    now = datetime.now(UTC)
    since = now - timedelta(seconds=RANGE_SECONDS[time_range])

    total_monitors = await db.scalar(select(func.count()).select_from(Monitor)) or 0
    active_monitors = (
        await db.scalar(
            select(func.count()).select_from(Monitor).where(Monitor.is_active.is_(True)),
        )
        or 0
    )

    status_rows = await db.execute(
        select(Monitor.current_status, func.count())
        .where(Monitor.is_active.is_(True))
        .group_by(Monitor.current_status),
    )
    status_counts = dict(status_rows.all())

    check_rows = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(MonitorCheck.status == "UP"),
            ).where(MonitorCheck.checked_at >= since),
        )
    ).one()
    total_checks, up_checks = check_rows
    overall_uptime = (
        round(float(up_checks) / float(total_checks) * 100.0, 2) if total_checks else None
    )

    average_latency = await db.scalar(
        select(func.avg(MonitorCheck.response_time_ms)).where(
            MonitorCheck.checked_at >= since,
            MonitorCheck.response_time_ms.is_not(None),
        ),
    )
    avg_response_time_ms = round(float(average_latency), 2) if average_latency is not None else None

    bucket = latency_bucket(time_range)
    series_rows = await db.execute(
        select(bucket, func.avg(MonitorCheck.response_time_ms))
        .where(
            MonitorCheck.checked_at >= since,
            MonitorCheck.response_time_ms.is_not(None),
        )
        .group_by(bucket)
        .order_by(bucket),
    )
    latency_series = [to_latency_point(row_bucket, average) for row_bucket, average in series_rows]

    monitors = list(
        (await db.scalars(select(Monitor).order_by(Monitor.created_at))).all(),
    )
    strips = await _status_strips(db, monitors)

    incident_rows = (
        await db.execute(
            select(Incident, Monitor.name)
            .join(Monitor, Monitor.id == Incident.monitor_id)
            .where(
                or_(
                    Incident.resolved_at.is_(None),
                    Incident.resolved_at >= since,
                    Incident.started_at >= since,
                )
            )
            .order_by(Incident.started_at.desc())
            .limit(RECENT_INCIDENT_LIMIT)
        )
    ).all()
    incidents = [
        IncidentSummary(
            id=incident.id,
            monitor_id=incident.monitor_id,
            monitor_name=monitor_name,
            cause=incident.cause,
            started_at=incident.started_at,
            resolved_at=incident.resolved_at,
            duration_seconds=max(
                0,
                int(((incident.resolved_at or now) - incident.started_at).total_seconds()),
            ),
        )
        for incident, monitor_name in incident_rows
    ]

    return DashboardSummary(
        total_monitors=total_monitors,
        active_monitors=active_monitors,
        paused_monitors=total_monitors - active_monitors,
        up_count=status_counts.get("UP", 0),
        down_count=status_counts.get("DOWN", 0) + status_counts.get("DEGRADED", 0),
        pending_count=status_counts.get("PENDING", 0),
        overall_uptime=overall_uptime,
        avg_response_time_ms=avg_response_time_ms,
        latency_series=latency_series,
        monitors=strips,
        incidents=incidents,
    )


async def _status_strips(
    db: AsyncSession,
    monitors: list[Monitor],
) -> list[MonitorStatusStrip]:
    statuses: dict[UUID, list[str]] = {monitor.id: [] for monitor in monitors}
    if monitors:
        since = datetime.now(UTC) - timedelta(days=STATUS_STRIP_LOOKBACK_DAYS)
        latest_checks = (
            select(MonitorCheck.status, MonitorCheck.checked_at)
            .where(
                MonitorCheck.monitor_id == Monitor.id,
                MonitorCheck.checked_at >= since,
            )
            .order_by(MonitorCheck.checked_at.desc())
            .limit(RECENT_STATUS_COUNT)
            .lateral("latest_checks")
        )
        rows = await db.execute(
            select(Monitor.id, latest_checks.c.status)
            .where(Monitor.id.in_([monitor.id for monitor in monitors]))
            .join(latest_checks, true())
            .order_by(Monitor.id, latest_checks.c.checked_at.asc())
        )
        for monitor_id, monitor_status in rows:
            statuses[monitor_id].append(monitor_status)

    return [
        MonitorStatusStrip(
            id=monitor.id,
            name=monitor.name,
            url=monitor.url,
            is_active=monitor.is_active,
            current_status=monitor.current_status,
            ssl_days_remaining=monitor.ssl_days_remaining,
            recent_statuses=statuses[monitor.id],
        )
        for monitor in monitors
    ]
