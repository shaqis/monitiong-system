"""add notification settings

Revision ID: b8c1d4e7a2f3
Revises: e8a4c1d2f6b9
Create Date: 2026-11-16 10:00:00.000000

A single row holds the admin-managed email settings. The row is optional: when
it is absent the worker falls back to the environment configuration. Secret
columns store Fernet tokens, never plaintext.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c1d4e7a2f3"
down_revision: str | None = "e8a4c1d2f6b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=20),
            server_default=sa.text("'smtp'"),
            nullable=False,
        ),
        sa.Column("from_address", sa.String(length=255), nullable=False),
        sa.Column("from_name", sa.String(length=120), nullable=False),
        sa.Column(
            "recipients",
            sa.ARRAY(sa.String(length=255)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("timeout_seconds", sa.Float(), server_default=sa.text("10"), nullable=False),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), server_default=sa.text("587"), nullable=False),
        sa.Column("smtp_starttls", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("smtp_ssl", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("smtp_username", sa.String(length=255), nullable=True),
        sa.Column("smtp_password_encrypted", sa.Text(), nullable=True),
        sa.Column("brevo_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_notification_settings_singleton"),
        sa.CheckConstraint(
            "provider IN ('smtp', 'brevo')",
            name="ck_notification_settings_provider",
        ),
        sa.CheckConstraint(
            "smtp_port BETWEEN 1 AND 65535",
            name="ck_notification_settings_smtp_port",
        ),
        sa.CheckConstraint(
            "NOT (smtp_starttls AND smtp_ssl)",
            name="ck_notification_settings_smtp_tls",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")
