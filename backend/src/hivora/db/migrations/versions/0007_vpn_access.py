"""VPN clients: server-side access rights, routing preset, expiry.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hivora.db.base import UTCDateTime

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vpn_peer") as batch:
        batch.add_column(sa.Column("access", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("routing", sa.String(10), nullable=False,
                                   server_default="default"))  # fmt: skip
        batch.add_column(sa.Column("expires_at", UTCDateTime(), nullable=True))
    # Clients that had their own allowed IPs keep them.
    op.execute("UPDATE vpn_peer SET routing = 'custom' "
               "WHERE allowed_ips IS NOT NULL AND allowed_ips != 'null'")  # fmt: skip


def downgrade() -> None:
    with op.batch_alter_table("vpn_peer") as batch:
        batch.drop_column("expires_at")
        batch.drop_column("routing")
        batch.drop_column("access")
