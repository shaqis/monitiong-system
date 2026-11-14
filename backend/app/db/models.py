from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'viewer')", name="ck_users_role"),)

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), server_default=text("'viewer'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        CheckConstraint("http_method IN ('GET', 'HEAD')", name="ck_monitors_http_method"),
        CheckConstraint(
            "interval_seconds IN (60, 300, 600, 1800)",
            name="ck_monitors_interval_seconds",
        ),
        CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 30",
            name="ck_monitors_timeout_seconds",
        ),
        CheckConstraint(
            "expected_status_code BETWEEN 100 AND 599",
            name="ck_monitors_expected_status_code",
        ),
        CheckConstraint(
            "current_status IN ('UP', 'DOWN', 'DEGRADED', 'PENDING')",
            name="ck_monitors_current_status",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_monitors_consecutive_failures",
        ),
        CheckConstraint(
            "url LIKE 'http://%' OR url LIKE 'https://%'",
            name="ck_monitors_url_scheme",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)
    http_method: Mapped[str] = mapped_column(String(10), server_default=text("'GET'"))
    interval_seconds: Mapped[int] = mapped_column(Integer, server_default=text("60"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    expected_status_code: Mapped[int] = mapped_column(Integer, server_default=text("200"))
    keyword: Mapped[str | None] = mapped_column(String(255))
    check_ssl: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    current_status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'PENDING'"),
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    ssl_days_remaining: Mapped[int | None] = mapped_column(Integer)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class MonitorCheck(Base):
    __tablename__ = "monitor_checks"
    __table_args__ = (
        CheckConstraint("status IN ('UP', 'DOWN')", name="ck_monitor_checks_status"),
        Index(
            "ix_monitor_checks_monitor_id_checked_at",
            "monitor_id",
            text("checked_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    monitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"),
    )
    status: Mapped[str] = mapped_column(String(20))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    keyword_matched: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    monitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"),
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cause: Mapped[str] = mapped_column(Text)


Index("ix_users_email_lower", func.lower(User.email), unique=True)
