"""A VPN DNS name aimed at one port of an app (vpn_dns_record.target_service, target_port),
and the job that applies the VPN's web proxy (vpn_web).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-05 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("deploy", "update", "remove", "pull", "start", "stop", "restart", "rollback", "adopt",
        "convert", "move_zone", "world_import", "world_delete", "backup",
        "backup_restore", "site_content", "site_file", "site_config", "host_package",
        "host_firewall", "host_route", "zone_action", "self_update", "host_upgrade",
        "host_reboot")  # fmt: skip
_NEW = (*_OLD, "vpn_web")


def _kind(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="jobkind", native_enum=False, create_constraint=True,
                   length=max(map(len, values)))  # fmt: skip


def upgrade() -> None:
    with op.batch_alter_table("vpn_dns_record") as batch:
        batch.add_column(sa.Column("target_service", sa.String(63), nullable=True))
        batch.add_column(sa.Column("target_port", sa.Integer(), nullable=True))
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_OLD), type_=_kind(_NEW),
                           existing_nullable=False)  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM job WHERE kind = 'vpn_web'")
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_NEW), type_=_kind(_OLD),
                           existing_nullable=False)  # fmt: skip
    with op.batch_alter_table("vpn_dns_record") as batch:
        batch.drop_column("target_port")
        batch.drop_column("target_service")
