"""Revisions: advanced settings (overrides) and hand-written compose files.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-28 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("app_revision") as batch:
        batch.add_column(sa.Column("overrides", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("custom_compose", sa.Boolean(), nullable=False,
                                   server_default="0"))  # fmt: skip


def downgrade() -> None:
    with op.batch_alter_table("app_revision") as batch:
        batch.drop_column("custom_compose")
        batch.drop_column("overrides")
