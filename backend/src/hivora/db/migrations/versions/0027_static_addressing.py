"""Static addressing: containers' fixed addresses, apps' own networks, hand-chosen zone
subnets (ip_assignment, app_network, zone.subnet_manual).

Zones keep their subnet when they have one (Administration, zones a VPN reaches); the others
get theirs from the Hivora range on the next start (addressing service), never here: the
range depends on the host's networks.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-05 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ip_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("network", sa.String(128), nullable=False),
        sa.Column("app", sa.String(63), nullable=False, index=True),
        sa.Column("service", sa.String(63), nullable=False),
        sa.Column("address", sa.String(15), nullable=False),
        sa.Column("manual", sa.Boolean(), nullable=False, server_default="0"),
        sa.UniqueConstraint("network", "address", name="uq_ip_assignment_address"),
        sa.UniqueConstraint("network", "app", "service", name="uq_ip_assignment_service"),
    )
    op.create_table(
        "app_network",
        sa.Column("app", sa.String(63), primary_key=True),
        sa.Column("subnet", sa.String(18), nullable=False, unique=True),
    )
    with op.batch_alter_table("zone") as batch:
        batch.add_column(sa.Column("subnet_manual", sa.Boolean(), nullable=False,
                                   server_default="0"))  # fmt: skip


def downgrade() -> None:
    with op.batch_alter_table("zone") as batch:
        batch.drop_column("subnet_manual")
    op.drop_table("app_network")
    op.drop_table("ip_assignment")
