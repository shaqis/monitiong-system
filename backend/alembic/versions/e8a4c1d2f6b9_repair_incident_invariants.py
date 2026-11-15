"""repair incident invariants for applied installs

Revision ID: e8a4c1d2f6b9
Revises: d7e1f2a3b4c5
Create Date: 2026-11-15 02:00:00.000000

d7e1f2a3b4c5 shipped in #18 and was corrected in #23 after installs had
recorded it, so those installs never re-ran the dedupe or the concurrent
check-index rebuild. This revision applies both corrections to every install.

The dedupe keeps the earliest open incident. The incidents table is locked in
SHARE mode first, which blocks a writer from inserting a new open incident
between the dedupe and the unique index build.

The check index is built under a temporary name, then the old index is dropped
and the new one renamed in one transaction. A failed build leaves the previous
index in place, and a leftover temporary index from an interrupted run is
dropped before the next attempt.

CREATE UNIQUE INDEX IF NOT EXISTS is deliberate. The autocommit block commits
the transaction that creates the unique index before the concurrent build
starts, so a failed build leaves the index behind. A plain create would make
the next upgrade fail on "relation already exists".

Downgrade is a no-op. The dedupe cannot be reversed, and the check index keeps
the definition it had before this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8a4c1d2f6b9"
down_revision: str | None = "d7e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_INDEX = "ix_monitor_checks_monitor_id_checked_at"
CHECK_INDEX_BUILD = f"{CHECK_INDEX}_build"

LOCK_INCIDENTS = "LOCK TABLE incidents IN SHARE MODE"

DEDUPE_OPEN_INCIDENTS = """
    UPDATE incidents
    SET resolved_at = now()
    WHERE resolved_at IS NULL
      AND id NOT IN (
        SELECT DISTINCT ON (monitor_id) id
        FROM incidents
        WHERE resolved_at IS NULL
        ORDER BY monitor_id, started_at ASC, id ASC
      )
"""

CREATE_OPEN_INCIDENT_INDEX = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_incidents_open_monitor
    ON incidents (monitor_id)
    WHERE resolved_at IS NULL
"""

DROP_BUILD_INDEX = f"DROP INDEX CONCURRENTLY IF EXISTS {CHECK_INDEX_BUILD}"
RENAME_BUILD_INDEX = f"ALTER INDEX {CHECK_INDEX_BUILD} RENAME TO {CHECK_INDEX}"


def upgrade() -> None:
    op.execute(LOCK_INCIDENTS)
    op.execute(DEDUPE_OPEN_INCIDENTS)
    op.execute(CREATE_OPEN_INCIDENT_INDEX)

    with op.get_context().autocommit_block():
        op.execute(DROP_BUILD_INDEX)
        op.create_index(
            CHECK_INDEX_BUILD,
            "monitor_checks",
            ["monitor_id", sa.text("checked_at DESC")],
            postgresql_include=["status"],
            postgresql_concurrently=True,
        )

    op.execute(f"DROP INDEX IF EXISTS {CHECK_INDEX}")
    op.execute(RENAME_BUILD_INDEX)


def downgrade() -> None:
    """The dedupe cannot be reversed, and the index shape is unchanged."""
