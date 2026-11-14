"""harden incident invariants

Revision ID: d7e1f2a3b4c5
Revises: c4d2e6f8a1b3
Create Date: 2026-11-15 01:00:00.000000

Deduplicates open incidents before adding the partial unique index. The
downgrade drops the index but cannot reopen incidents closed by the dedupe.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e1f2a3b4c5"
down_revision: str | None = "c4d2e6f8a1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEDUPE_OPEN_INCIDENTS = """
    UPDATE incidents
    SET resolved_at = now()
    WHERE resolved_at IS NULL
      AND id NOT IN (
        SELECT DISTINCT ON (monitor_id) id
        FROM incidents
        WHERE resolved_at IS NULL
        ORDER BY monitor_id, started_at DESC, id DESC
      )
"""


def upgrade() -> None:
    op.execute(DEDUPE_OPEN_INCIDENTS)
    op.create_index(
        "uq_incidents_open_monitor",
        "incidents",
        ["monitor_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.drop_index("ix_monitor_checks_monitor_id_checked_at", table_name="monitor_checks")
    op.create_index(
        "ix_monitor_checks_monitor_id_checked_at",
        "monitor_checks",
        ["monitor_id", sa.text("checked_at DESC")],
        postgresql_include=["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_monitor_checks_monitor_id_checked_at", table_name="monitor_checks")
    op.create_index(
        "ix_monitor_checks_monitor_id_checked_at",
        "monitor_checks",
        ["monitor_id", sa.text("checked_at DESC")],
    )
    op.drop_index("uq_incidents_open_monitor", table_name="incidents")
