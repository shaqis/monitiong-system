from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.analytics import latency_bucket, to_latency_point
from app.core.deps import get_current_user, require_admin
from app.core.errors import public_errors
from app.db.models import Incident, Monitor, MonitorCheck, User
from app.db.session import get_db
from app.schemas.monitor import (
    RANGE_SECONDS,
    CheckHistoryResponse,
    CheckResponse,
    MonitorCreate,
    MonitorDetailResponse,
    MonitorIncident,
    MonitorListItem,
    MonitorResponse,
    MonitorUpdate,
    StatusFilter,
    TimeRange,
    normalize_http_url,
)
from app.worker.checker import (
    TARGET_FIELDS,
    CheckAlreadyRunning,
    CheckRunner,
    MonitorChanged,
    MonitorNotFound,
    MonitorPaused,
)

router = APIRouter()


def get_check_runner(request: Request) -> CheckRunner:
    runner = getattr(request.app.state, "check_runner", None)
    if not isinstance(runner, CheckRunner):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monitoring engine is not running",
        )
    return runner


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")


async def _resolve_open_incidents(
    db: AsyncSession,
    monitor_id: UUID,
    resolved_at: datetime,
) -> None:
    """Close every open incident for one monitor at a single timestamp."""
    await db.execute(
        update(Incident)
        .where(
            and_(
                Incident.monitor_id == monitor_id,
                Incident.resolved_at.is_(None),
            )
        )
        .values(resolved_at=resolved_at)
    )


async def _reset_target_state(
    db: AsyncSession,
    monitor: Monitor,
    resolved_at: datetime,
) -> None:
    """Restart the check cycle after the probed target changed."""
    monitor.current_status = "PENDING"
    monitor.consecutive_failures = 0
    monitor.last_checked_at = None
    await _resolve_open_incidents(db, monitor.id, resolved_at)


def _stored_target(monitor: Monitor, field: str) -> object:
    """The stored target value in the same shape a validated payload has."""
    value = getattr(monitor, field)
    if field != "url":
        return value
    try:
        return normalize_http_url(value)
    except ValueError:
        # A row written before the validator can hold a URL it rejects.
        return value


def _percent(up: int, total: int) -> float | None:
    if not total:
        return None
    return round(float(up) / float(total) * 100.0, 2)


async def _uptime_map(
    db: AsyncSession,
    monitor_ids: list[UUID],
    since: datetime,
) -> dict[UUID, float | None]:
    uptimes: dict[UUID, float | None] = dict.fromkeys(monitor_ids)
    if not monitor_ids:
        return uptimes

    rows = await db.execute(
        select(
            MonitorCheck.monitor_id,
            func.count().label("total"),
            func.count().filter(MonitorCheck.status == "UP").label("up"),
        )
        .where(
            MonitorCheck.monitor_id.in_(monitor_ids),
            MonitorCheck.checked_at >= since,
        )
        .group_by(MonitorCheck.monitor_id)
    )
    for monitor_id, total, up in rows:
        uptimes[monitor_id] = _percent(up, total)
    return uptimes


async def _latest_latency_map(
    db: AsyncSession,
    monitor_ids: list[UUID],
) -> dict[UUID, int | None]:
    latencies: dict[UUID, int | None] = dict.fromkeys(monitor_ids)
    if not monitor_ids:
        return latencies

    rows = await db.execute(
        select(MonitorCheck.monitor_id, MonitorCheck.response_time_ms)
        .ext(distinct_on(MonitorCheck.monitor_id))
        .where(MonitorCheck.monitor_id.in_(monitor_ids))
        .order_by(MonitorCheck.monitor_id, MonitorCheck.checked_at.desc())
    )
    for monitor_id, response_time_ms in rows:
        latencies[monitor_id] = response_time_ms
    return latencies


@router.get("", response_model=list[MonitorListItem])
async def list_monitors(
    search: str | None = Query(default=None, max_length=255),
    monitor_status: StatusFilter = Query(default="all", alias="status"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MonitorListItem]:
    statement = select(Monitor).order_by(Monitor.created_at.desc())

    if search is not None and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(Monitor.name.ilike(pattern), Monitor.url.ilike(pattern)),
        )

    if monitor_status == "up":
        statement = statement.where(
            Monitor.is_active.is_(True),
            Monitor.current_status == "UP",
        )
    elif monitor_status == "down":
        statement = statement.where(
            Monitor.is_active.is_(True),
            Monitor.current_status.in_(("DOWN", "DEGRADED")),
        )
    elif monitor_status == "paused":
        statement = statement.where(Monitor.is_active.is_(False))

    monitors = list((await db.scalars(statement)).all())
    monitor_ids = [monitor.id for monitor in monitors]
    now = datetime.now(UTC)
    uptimes = await _uptime_map(db, monitor_ids, now - timedelta(hours=24))
    latencies = await _latest_latency_map(db, monitor_ids)

    items: list[MonitorListItem] = []
    for monitor in monitors:
        item = MonitorListItem.model_validate(monitor)
        item.uptime_24h = uptimes.get(monitor.id)
        item.last_response_time_ms = latencies.get(monitor.id)
        items.append(item)
    return items


@router.post("", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    payload: MonitorCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    monitor = Monitor(**payload.model_dump(), created_by=admin.id)
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)
    return monitor


@router.get("/{monitor_id}", response_model=MonitorDetailResponse)
async def get_monitor(
    monitor_id: UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorDetailResponse:
    monitor = await db.get(Monitor, monitor_id)
    if monitor is None:
        raise _not_found()

    now = datetime.now(UTC)
    detail = MonitorDetailResponse.model_validate(monitor)
    detail.uptime_24h = (await _uptime_map(db, [monitor.id], now - timedelta(hours=24))).get(
        monitor.id
    )
    detail.uptime_7d = (await _uptime_map(db, [monitor.id], now - timedelta(days=7))).get(
        monitor.id
    )
    detail.uptime_30d = (await _uptime_map(db, [monitor.id], now - timedelta(days=30))).get(
        monitor.id
    )
    detail.last_response_time_ms = await db.scalar(
        select(MonitorCheck.response_time_ms)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(MonitorCheck.checked_at.desc())
        .limit(1)
    )

    since = now - timedelta(days=30)
    incident_rows = list(
        (
            await db.scalars(
                select(Incident)
                .where(
                    Incident.monitor_id == monitor.id,
                    or_(
                        Incident.resolved_at.is_(None),
                        Incident.resolved_at >= since,
                        Incident.started_at >= since,
                    ),
                )
                .order_by(Incident.started_at.desc())
                .limit(20)
            )
        ).all()
    )
    detail.recent_incidents = [
        MonitorIncident(
            id=incident.id,
            cause=incident.cause,
            started_at=incident.started_at,
            resolved_at=incident.resolved_at,
            duration_seconds=max(
                0,
                int(((incident.resolved_at or now) - incident.started_at).total_seconds()),
            ),
        )
        for incident in incident_rows
    ]
    return detail


@router.patch("/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: UUID,
    payload: MonitorUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    monitor = await db.scalar(
        select(Monitor).where(Monitor.id == monitor_id).with_for_update(),
    )
    if monitor is None:
        raise _not_found()

    merged = {field: getattr(monitor, field) for field in MonitorCreate.model_fields}
    for field in payload.model_fields_set:
        merged[field] = getattr(payload, field)

    try:
        validated = MonitorCreate.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=public_errors(exc),
        ) from exc

    target_changed = any(
        getattr(validated, field) != _stored_target(monitor, field) for field in TARGET_FIELDS
    )

    for field in MonitorCreate.model_fields:
        setattr(monitor, field, getattr(validated, field))

    if target_changed:
        await _reset_target_state(db, monitor, datetime.now(UTC))

    if payload.is_active is False:
        # The next cycle starts from zero, so a resume needs two strikes.
        monitor.consecutive_failures = 0
        await _resolve_open_incidents(db, monitor.id, datetime.now(UTC))

    await db.commit()
    await db.refresh(monitor)
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    monitor_id: UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    runner: CheckRunner = Depends(get_check_runner),
) -> None:
    monitor = await db.get(Monitor, monitor_id)
    if monitor is None:
        raise _not_found()

    await db.delete(monitor)
    await db.commit()
    runner.forget(monitor_id)


@router.post(
    "/{monitor_id}/check-now",
    response_model=CheckResponse,
    status_code=status.HTTP_201_CREATED,
)
async def check_monitor_now(
    monitor_id: UUID,
    _: User = Depends(require_admin),
    runner: CheckRunner = Depends(get_check_runner),
) -> MonitorCheck:
    try:
        return await runner.run(monitor_id)
    except MonitorNotFound:
        raise _not_found() from None
    except MonitorPaused:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Monitor is paused",
        ) from None
    except CheckAlreadyRunning:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A check is already running for this monitor",
        ) from None
    except MonitorChanged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Monitor changed during check",
        ) from None


@router.get("/{monitor_id}/checks", response_model=CheckHistoryResponse)
async def list_monitor_checks(
    monitor_id: UUID,
    time_range: TimeRange = Query(default="24h", alias="range"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckHistoryResponse:
    exists = await db.scalar(select(Monitor.id).where(Monitor.id == monitor_id))
    if exists is None:
        raise _not_found()

    since = datetime.now(UTC) - timedelta(seconds=RANGE_SECONDS[time_range])
    window = and_(
        MonitorCheck.monitor_id == monitor_id,
        MonitorCheck.checked_at >= since,
    )

    total = await db.scalar(select(func.count()).select_from(MonitorCheck).where(window)) or 0
    items = list(
        (
            await db.scalars(
                select(MonitorCheck)
                .where(window)
                .order_by(MonitorCheck.checked_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )

    bucket = latency_bucket(time_range)
    rows = await db.execute(
        select(bucket, func.avg(MonitorCheck.response_time_ms))
        .where(window, MonitorCheck.response_time_ms.is_not(None))
        .group_by(bucket)
        .order_by(bucket)
    )
    series = [to_latency_point(row_bucket, average) for row_bucket, average in rows]

    return CheckHistoryResponse(
        items=[CheckResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
        series=series,
    )
