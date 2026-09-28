"""Topology: declared nodes and edges, node positions.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-29 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topology_node",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
    )
    op.create_table(
        "topology_edge",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("target", sa.String(40), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
    )
    op.create_table(
        "topology_layout",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("topology_layout")
    op.drop_table("topology_edge")
    op.drop_table("topology_node")
