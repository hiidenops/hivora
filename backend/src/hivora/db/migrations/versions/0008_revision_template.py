"""Revisions remember their template version (restore an earlier revision).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-28 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("app_revision") as batch:
        batch.add_column(sa.Column("template_version_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_app_revision_template_version", "template_version",
                                 ["template_version_id"], ["id"])  # fmt: skip
    # The latest revision of each app was compiled from the app's current version.
    op.execute(
        "UPDATE app_revision SET template_version_id = (SELECT template_version_id "
        "FROM application WHERE application.id = app_revision.app_id) "
        "WHERE number = (SELECT MAX(r.number) FROM app_revision r "
        "WHERE r.app_id = app_revision.app_id)"
    )


def downgrade() -> None:
    with op.batch_alter_table("app_revision") as batch:
        batch.drop_constraint("fk_app_revision_template_version", type_="foreignkey")
        batch.drop_column("template_version_id")
