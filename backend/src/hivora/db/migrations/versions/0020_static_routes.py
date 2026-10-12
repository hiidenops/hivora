"""The host's static IPv4 routes (static_route), and the job kind that applies them to the
host (host_route).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-12 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hivora.db.base import UTCDateTime

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("deploy", "update", "remove", "pull", "start", "stop", "restart", "rollback", "adopt",
        "convert", "move_zone", "world_import", "world_delete", "backup",
        "backup_restore", "site_content", "site_file", "site_config", "host_package",
        "host_firewall")  # fmt: skip
_NEW = (*_OLD, "host_route")


def _kind(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="jobkind", native_enum=False, create_constraint=True,
                   length=max(map(len, values)))  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "static_route",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("destination", sa.String(18), nullable=False),
        sa.Column("gateway", sa.String(15), nullable=False),
        sa.Column("dev", sa.String(15), nullable=True),
        sa.Column("metric", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("destination"),
        sa.CheckConstraint("destination != '' AND gateway != ''", name="not_empty"),
        sa.CheckConstraint("metric IS NULL OR metric BETWEEN 0 AND 4294967295",
                           name="metric_range"),
    )  # fmt: skip
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_OLD), type_=_kind(_NEW),
                           existing_nullable=False)  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM job WHERE kind = 'host_route'")
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_NEW), type_=_kind(_OLD),
                           existing_nullable=False)  # fmt: skip
    op.drop_table("static_route")
