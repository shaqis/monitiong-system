from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlparse, urlunparse
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

HttpMethod = Literal["GET", "HEAD"]
MonitorStatusValue = Literal["UP", "DOWN", "DEGRADED", "PENDING"]
IntervalSeconds = Literal[60, 300, 600, 1800]
TimeRange = Literal["1h", "24h", "7d", "30d"]
StatusFilter = Literal["all", "up", "down", "paused"]

RANGE_SECONDS: dict[TimeRange, int] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}

RANGE_BUCKET_SECONDS: dict[TimeRange, int] = {
    "1h": 60,
    "24h": 900,
    "7d": 3600,
    "30d": 21600,
}

MAX_URL_LENGTH = 2048
MAX_KEYWORD_LENGTH = 255


def normalize_http_url(value: str) -> str:
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("URL must include a host")
    return urlunparse(parsed._replace(scheme=scheme))


Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
HttpUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_URL_LENGTH),
    AfterValidator(normalize_http_url),
]
Keyword = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_KEYWORD_LENGTH),
]
ExpectedStatusCode = Annotated[int, Field(ge=100, le=599)]


class MonitorTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    http_method: HttpMethod = "GET"
    expected_status_code: ExpectedStatusCode = 200
    keyword: Keyword | None = None


class MonitorCreate(MonitorTarget):
    name: Name
    interval_seconds: IntervalSeconds = 60
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    check_ssl: bool = True
    is_active: bool = True


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    url: HttpUrl | None = None
    http_method: HttpMethod | None = None
    interval_seconds: IntervalSeconds | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    expected_status_code: ExpectedStatusCode | None = None
    keyword: Keyword | None = None
    check_ssl: bool | None = None
    is_active: bool | None = None


class MonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    http_method: HttpMethod
    interval_seconds: int
    timeout_seconds: int
    expected_status_code: int
    keyword: str | None
    check_ssl: bool
    is_active: bool
    current_status: MonitorStatusValue
    consecutive_failures: int
    ssl_days_remaining: int | None
    last_checked_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class MonitorListItem(MonitorResponse):
    uptime_24h: float | None = None
    last_response_time_ms: int | None = None


class MonitorIncident(BaseModel):
    id: UUID
    cause: str
    started_at: datetime
    resolved_at: datetime | None
    duration_seconds: int


class MonitorDetailResponse(MonitorListItem):
    uptime_7d: float | None = None
    uptime_30d: float | None = None
    recent_incidents: list[MonitorIncident] = Field(default_factory=list)


class CheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: UUID
    status: Literal["UP", "DOWN"]
    status_code: int | None
    response_time_ms: int | None
    keyword_matched: bool | None
    error_message: str | None
    checked_at: datetime


class LatencyPoint(BaseModel):
    bucket: datetime
    avg_response_time_ms: float | None


class CheckHistoryResponse(BaseModel):
    items: list[CheckResponse]
    total: int
    limit: int
    offset: int
    series: list[LatencyPoint]
