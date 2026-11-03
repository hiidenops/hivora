"""Public domains served by the HTTPS proxy (proxy_route).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-03 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proxy_route",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(253), nullable=False, unique=True),
        sa.Column("app_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), nullable=False),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_table("proxy_route")
