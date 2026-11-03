"""Names answered by a VPN's own DNS (vpn_dns_record).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-03 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vpn_dns_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vpn_app_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(253), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("target_app_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), nullable=True),
        sa.UniqueConstraint("vpn_app_id", "name"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_table("vpn_dns_record")
