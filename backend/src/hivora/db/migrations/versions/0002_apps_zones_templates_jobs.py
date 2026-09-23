"""Create apps, zones, template versions and jobs tables; seed the Administration zone.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23 15:38:54.008272
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "template_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("api_version", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_template_version")),
        sa.UniqueConstraint("source", "slug", "version", name=op.f("uq_template_version_source")),
    )
    zone = op.create_table(
        "zone",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "network_mode",
            sa.Enum(
                "none",
                "shared",
                "isolated",
                "custom",
                name="networkmode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("docker_network_id", sa.String(length=64), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zone")),
        sa.UniqueConstraint("slug", name=op.f("uq_zone_slug")),
    )
    # System zone created at install, cannot be deleted (docs section 9).
    op.bulk_insert(
        zone,
        [
            {
                "slug": "administration",
                "name": "Administration",
                "color": "#64748b",
                "icon": "shield",
                "description": "",
                "network_mode": "none",
                "sort_order": 0,
                "is_system": True,
                "created_at": datetime.now(UTC).replace(tzinfo=None),
            }
        ],
    )
    op.create_table(
        "application",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=True),
        sa.Column(
            "origin",
            sa.Enum(
                "template",
                "image",
                "adopted",
                "compose",
                name="origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("template_version_id", sa.Integer(), nullable=True),
        sa.Column("current_revision_id", sa.Integer(), nullable=True),
        sa.Column(
            "desired_state",
            sa.Enum(
                "running", "stopped", name="desiredstate", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("icon", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["current_revision_id"],
            ["app_revision.id"],
            name=op.f("fk_application_current_revision_id_app_revision"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["template_version.id"],
            name=op.f("fk_application_template_version_id_template_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"], ["zone.id"], name=op.f("fk_application_zone_id_zone"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application")),
        sa.UniqueConstraint("slug", name=op.f("uq_application_slug")),
    )
    op.create_table(
        "app_revision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("compose_yaml", sa.Text(), nullable=False),
        sa.Column("diff_from_previous", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "applied",
                "failed",
                "superseded",
                name="revisionstatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["application.id"],
            name=op.f("fk_app_revision_app_id_application"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_revision")),
        sa.UniqueConstraint("app_id", "number", name=op.f("uq_app_revision_app_id")),
    )
    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "deploy",
                "update",
                "remove",
                "pull",
                "start",
                "stop",
                "restart",
                "rollback",
                "adopt",
                "convert",
                "move_zone",
                name="jobkind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("app_id", sa.Integer(), nullable=True),
        sa.Column("app_slug", sa.String(length=63), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
                name="jobstatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("log", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["application.id"],
            name=op.f("fk_job_app_id_application"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job")),
    )
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_app_id"), ["app_id"], unique=False)
        batch_op.create_index("ix_job_status_id", ["status", "id"], unique=False)

    op.create_table(
        "secret",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=63), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["application.id"],
            name=op.f("fk_secret_app_id_application"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secret")),
        sa.UniqueConstraint("app_id", "key", name=op.f("uq_secret_app_id")),
    )
    op.create_table(
        "service",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("image", sa.String(length=500), nullable=False),
        sa.Column("image_digest", sa.String(length=100), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "main",
                "database",
                "cache",
                "sidecar",
                name="servicerole",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("restart_policy", sa.String(length=20), nullable=False),
        sa.Column("cpu_limit", sa.Float(), nullable=True),
        sa.Column("mem_limit", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["application.id"],
            name=op.f("fk_service_app_id_application"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service")),
        sa.UniqueConstraint("app_id", "name", name=op.f("uq_service_app_id")),
    )
    op.create_table(
        "port_binding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("host_ip", sa.String(length=45), nullable=True),
        sa.Column("host_port", sa.Integer(), nullable=True),
        sa.Column("container_port", sa.Integer(), nullable=False),
        sa.Column("protocol", sa.String(length=3), nullable=False),
        sa.Column("purpose", sa.String(length=10), nullable=False),
        sa.Column(
            "exposure",
            sa.Enum(
                "public",
                "lan",
                "vpn",
                "internal",
                name="exposure",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["service.id"],
            name=op.f("fk_port_binding_service_id_service"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_port_binding")),
    )
    op.create_table(
        "volume_mount",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("named", "bind", name="volumekind", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("target", sa.String(length=1000), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("backup", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["service.id"],
            name=op.f("fk_volume_mount_service_id_service"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_volume_mount")),
    )


def downgrade() -> None:
    op.drop_table("volume_mount")
    op.drop_table("port_binding")
    op.drop_table("service")
    op.drop_table("secret")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_index("ix_job_status_id")
        batch_op.drop_index(batch_op.f("ix_job_app_id"))

    op.drop_table("job")
    op.drop_table("app_revision")
    op.drop_table("application")
    op.drop_table("zone")
    op.drop_table("template_version")
