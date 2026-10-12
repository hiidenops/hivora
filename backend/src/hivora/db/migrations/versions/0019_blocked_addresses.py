"""Addresses blocked on the host and its Docker apps (blocked_address), and the job kind that
applies them to the host (host_firewall).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-12 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hivora.db.base import UTCDateTime

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("deploy", "update", "remove", "pull", "start", "stop", "restart", "rollback", "adopt",
        "convert", "move_zone", "world_import", "world_delete", "backup",
        "backup_restore", "site_content", "site_file", "site_config", "host_package")  # fmt: skip
_NEW = (*_OLD, "host_firewall")


def _kind(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="jobkind", native_enum=False, create_constraint=True,
                   length=max(map(len, values)))  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "blocked_address",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("address", sa.String(45), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("address"),
        sa.CheckConstraint("address != ''", name="address_not_empty"),
    )  # fmt: skip
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_OLD), type_=_kind(_NEW),
                           existing_nullable=False)  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM job WHERE kind = 'host_firewall'")
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_NEW), type_=_kind(_OLD),
                           existing_nullable=False)  # fmt: skip
    op.drop_table("blocked_address")
