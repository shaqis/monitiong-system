from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IncidentOpened:
    monitor_id: UUID
    monitor_name: str
    monitor_url: str
    cause: str
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class IncidentResolved:
    monitor_id: UUID
    monitor_name: str
    monitor_url: str
    started_at: datetime
    resolved_at: datetime
    duration_seconds: int


type IncidentEvent = IncidentOpened | IncidentResolved
