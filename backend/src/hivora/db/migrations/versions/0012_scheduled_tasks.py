"""Scheduled tasks (simplified cron) per app.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-28 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hivora.db.base import UTCDateTime

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("service", sa.String(63), nullable=True),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("frequency", sa.String(10), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("every_hours", sa.Integer(), nullable=False),
        sa.Column("next_run_at", UTCDateTime(), nullable=True),
        sa.Column("last_run_at", UTCDateTime(), nullable=True),
        sa.Column("last_status", sa.String(10), nullable=True),
        sa.Column("last_output", sa.Text(), nullable=False),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_table("scheduled_task")
