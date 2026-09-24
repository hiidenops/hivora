"""Job kinds for game worlds: import and delete.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("deploy", "update", "remove", "pull", "start", "stop", "restart", "rollback", "adopt",
        "convert", "move_zone")  # fmt: skip
_NEW = (*_OLD, "world_import", "world_delete")


def _kind(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="jobkind", native_enum=False, create_constraint=True,
                   length=max(map(len, values)))  # fmt: skip


def upgrade() -> None:
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_OLD), type_=_kind(_NEW),
                           existing_nullable=False)  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM job WHERE kind IN ('world_import', 'world_delete')")
    with op.batch_alter_table("job") as batch:
        batch.alter_column("kind", existing_type=_kind(_NEW), type_=_kind(_OLD),
                           existing_nullable=False)  # fmt: skip
