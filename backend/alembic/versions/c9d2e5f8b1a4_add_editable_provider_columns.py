"""add editable provider columns

Revision ID: c9d2e5f8b1a4
Revises: b8c1d4e7a2f3
Create Date: 2026-11-16 12:00:00.000000

Mailgun and Mailtrap become editable from the admin settings page, so the
singleton row stores their non-secret details and Fernet tokens for their
credentials. The provider check constraint accepts all four providers.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d2e5f8b1a4"
down_revision: str | None = "b8c1d4e7a2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_settings",
        sa.Column("mailgun_api_key_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "notification_settings",
        sa.Column("mailgun_domain", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "notification_settings",
        sa.Column("mailgun_api_url", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "notification_settings",
        sa.Column("mailtrap_api_token_encrypted", sa.Text(), nullable=True),
    )
    op.drop_constraint(
        "ck_notification_settings_provider",
        "notification_settings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_notification_settings_provider",
        "notification_settings",
        "provider IN ('smtp', 'brevo', 'mailgun', 'mailtrap')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_notification_settings_provider",
        "notification_settings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_notification_settings_provider",
        "notification_settings",
        "provider IN ('smtp', 'brevo')",
    )
    op.drop_column("notification_settings", "mailtrap_api_token_encrypted")
    op.drop_column("notification_settings", "mailgun_api_url")
    op.drop_column("notification_settings", "mailgun_domain")
    op.drop_column("notification_settings", "mailgun_api_key_encrypted")
