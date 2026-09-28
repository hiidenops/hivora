"""VPN clients: a preshared key each (encrypted).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-28 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vpn_peer") as batch:
        batch.add_column(sa.Column("psk_nonce", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("psk", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vpn_peer") as batch:
        batch.drop_column("psk")
        batch.drop_column("psk_nonce")
