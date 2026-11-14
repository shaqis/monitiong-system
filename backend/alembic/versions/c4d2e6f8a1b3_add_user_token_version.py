"""add user token version

Revision ID: c4d2e6f8a1b3
Revises: a883d511c882
Create Date: 2026-11-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d2e6f8a1b3"
down_revision: str | None = "a883d511c882"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
