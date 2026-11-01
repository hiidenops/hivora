"""A zone's own subnet (zone.subnet): chosen by Hivora next to the VPN's network when a VPN
reaches the zone, its Docker network is created (or recreated) with it.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-01 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("zone") as batch:
        batch.add_column(sa.Column("subnet", sa.String(43), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("zone") as batch:
        batch.drop_column("subnet")
