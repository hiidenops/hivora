"""A zone's start order: the dependencies between its apps (app_dependency), how long an app
may take to be healthy (zone.start_timeout_s), and the job kind that starts, stops or
restarts a zone in that order (zone_action).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-13 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("deploy", "update", "remove", "pull", "start", "stop", "restart", "rollback", "adopt",
        "convert", "move_zone", "world_import", "world_delete", "backup",
        "backup_restore", "site_content", "site_file", "site_config", "host_package",
        "host_firewall", "host_route")  # fmt: skip
_NEW = (*_OLD, "zone_action")


def _kind(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="jobkind", native_enum=False, create_constraint=True,
                   length=max(map(len, values)))  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "app_dependency",
        sa.Column("app_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("depends_on_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), primary_key=True),
        sa.CheckConstraint("app_id != depends_on_id", name="not_self"),
    )  # fmt: skip
    op.create_index("ix_app_dependency_depends_on_id", "app_dependency", ["depends_on_id"])
    with op.batch_alter_table("zone") as batch:
        batch.add_column(sa.Column("start_timeout_s", sa.Integer(), nullable=False,
                                   server_default="120"))  # fmt: skip
        batch.create_check_constraint("start_timeout_range", "start_timeout_s BETWEEN 10 AND 3600")
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_OLD), type_=_kind(_NEW),
                           existing_nullable=False)  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM job WHERE kind = 'zone_action'")
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_NEW), type_=_kind(_OLD),
                           existing_nullable=False)  # fmt: skip
    with op.batch_alter_table("zone") as batch:
        batch.drop_constraint("start_timeout_range", type_="check")
        batch.drop_column("start_timeout_s")
    op.drop_index("ix_app_dependency_depends_on_id", table_name="app_dependency")
    op.drop_table("app_dependency")
