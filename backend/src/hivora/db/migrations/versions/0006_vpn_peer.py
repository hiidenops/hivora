"""VPN peers: Hivora manages WireGuard itself (keys and config, no wg-easy API).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vpn_peer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), nullable=False),
        sa.Column("server", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("address", sa.String(45), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_ips", sa.JSON(), nullable=True),
        sa.Column("public_key", sa.String(44), nullable=False),
        sa.Column("private_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("private_key", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("app_id", "address"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_table("vpn_peer")
