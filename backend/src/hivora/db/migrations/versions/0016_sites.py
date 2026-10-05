"""Sites hosted by an nginx app; each existing static site becomes the main site of its app.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-02 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hivora.db.base import UTCDateTime

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.Integer(),
                  sa.ForeignKey("application.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("root", sa.String(63), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("server_name", sa.String(253), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("app_id", "slug", name="uq_site_app_id_slug"),
        sa.UniqueConstraint("app_id", "root", name="uq_site_app_id_root"),
        sa.UniqueConstraint("app_id", "port", name="uq_site_app_id_port"),
        sa.CheckConstraint(
            "(root = '' AND port IS NULL) OR (root != '' AND port IS NOT NULL)",
            name="main_iff_no_port",
        ),
        sa.CheckConstraint("port IS NULL OR port BETWEEN 1 AND 65535", name="port_range"),
        sa.CheckConstraint("root = '' OR root = slug", name="root_is_slug"),
        sa.CheckConstraint("slug != ''", name="slug_not_empty"),
    )  # fmt: skip
    # Each static site so far is one nginx serving its html volume: its main site.
    # No file or folder is touched.
    op.execute(
        "INSERT INTO site (app_id, slug, name, root, port, server_name, enabled, created_at) "
        "SELECT id, 'main', name, '', NULL, NULL, 1, created_at FROM application "
        "WHERE kind = 'static-site'"
    )


def downgrade() -> None:
    op.drop_table("site")
