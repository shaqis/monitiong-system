from datetime import datetime

from sqlalchemy import ColumnElement, func

from app.db.models import MonitorCheck
from app.schemas.monitor import RANGE_BUCKET_SECONDS, LatencyPoint, TimeRange


def latency_bucket(time_range: TimeRange) -> ColumnElement[datetime]:
    """Bucket check timestamps for the requested range."""
    return func.date_bin(
        func.make_interval(0, 0, 0, 0, 0, 0, RANGE_BUCKET_SECONDS[time_range]),
        MonitorCheck.checked_at,
        func.to_timestamp(0),
    ).label("bucket")


def to_latency_point(bucket: datetime, average: float | None) -> LatencyPoint:
    return LatencyPoint(
        bucket=bucket,
        avg_response_time_ms=round(float(average), 2) if average is not None else None,
    )
