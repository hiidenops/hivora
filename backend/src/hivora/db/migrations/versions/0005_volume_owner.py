"""Volume owner: images running as a fixed UID (e.g. 10001) get their folder.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("volume_mount") as batch:
        batch.add_column(sa.Column("owner", sa.String(21), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("volume_mount") as batch:
        batch.drop_column("owner")
