from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.monitor import LatencyPoint, MonitorStatusValue


class MonitorStatusStrip(BaseModel):
    id: UUID
    name: str
    url: str
    is_active: bool
    current_status: MonitorStatusValue
    ssl_days_remaining: int | None
    recent_statuses: list[Literal["UP", "DOWN"]]


class IncidentSummary(BaseModel):
    id: UUID
    monitor_id: UUID
    monitor_name: str
    cause: str
    started_at: datetime
    resolved_at: datetime | None
    duration_seconds: int


class DashboardSummary(BaseModel):
    total_monitors: int
    active_monitors: int
    paused_monitors: int
    up_count: int
    down_count: int
    pending_count: int
    overall_uptime: float | None
    avg_response_time_ms: float | None
    latency_series: list[LatencyPoint]
    monitors: list[MonitorStatusStrip]
    incidents: list[IncidentSummary]
