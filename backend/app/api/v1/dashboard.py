from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import Incident, Monitor, MonitorCheck, User
from app.db.session import get_db
from app.schemas.dashboard import DashboardSummary, IncidentSummary, MonitorStatusStrip
from app.schemas.monitor import (
    RANGE_BUCKET_SECONDS,
    RANGE_SECONDS,
    LatencyPoint,
    TimeRange,
)

router = APIRouter()

RECENT_STATUS_COUNT = 20
RECENT_INCIDENT_LIMIT = 20


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

    bucket = func.date_bin(
        func.make_interval(0, 0, 0, 0, 0, 0, RANGE_BUCKET_SECONDS[time_range]),
        MonitorCheck.checked_at,
        func.to_timestamp(0),
    ).label("bucket")
    series_rows = await db.execute(
        select(bucket, func.avg(MonitorCheck.response_time_ms))
        .where(
            MonitorCheck.checked_at >= since,
            MonitorCheck.response_time_ms.is_not(None),
        )
        .group_by(bucket)
        .order_by(bucket),
    )
    latency_series = [
        LatencyPoint(
            bucket=row_bucket,
            avg_response_time_ms=round(float(average), 2) if average is not None else None,
        )
        for row_bucket, average in series_rows
    ]

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
        ranked = (
            select(
                MonitorCheck.monitor_id,
                MonitorCheck.status,
                MonitorCheck.checked_at,
                func.row_number()
                .over(
                    partition_by=MonitorCheck.monitor_id,
                    order_by=MonitorCheck.checked_at.desc(),
                )
                .label("position"),
            )
            .where(MonitorCheck.monitor_id.in_([monitor.id for monitor in monitors]))
            .subquery()
        )
        rows = await db.execute(
            select(ranked.c.monitor_id, ranked.c.status)
            .where(ranked.c.position <= RECENT_STATUS_COUNT)
            .order_by(ranked.c.monitor_id, ranked.c.checked_at.asc()),
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
