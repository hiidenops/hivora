"""Applications and everything describing their intended state.

Runtime state (running, health, CPU) is never stored here: see ``state``.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hivora.db.base import Base, UTCDateTime, str_enum


class Origin(StrEnum):
    TEMPLATE = "template"
    IMAGE = "image"
    ADOPTED = "adopted"
    COMPOSE = "compose"


class DesiredState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


class RevisionStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ServiceRole(StrEnum):
    MAIN = "main"
    DATABASE = "database"
    CACHE = "cache"
    SIDECAR = "sidecar"


class Exposure(StrEnum):
    PUBLIC = "public"
    LAN = "lan"
    VPN = "vpn"
    INTERNAL = "internal"


class VolumeKind(StrEnum):
    NAMED = "named"
    BIND = "bind"


HOSTING_KIND = "static-site"  # application.kind of an nginx that hosts sites


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zone.id", ondelete="SET NULL"))
    origin: Mapped[Origin] = mapped_column(str_enum(Origin))
    template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("template_version.id", ondelete="RESTRICT")
    )
    current_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_revision.id", ondelete="SET NULL", use_alter=True)
    )
    desired_state: Mapped[DesiredState] = mapped_column(
        str_enum(DesiredState), default=DesiredState.RUNNING
    )
    icon: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str | None] = mapped_column(String(32))  # HOSTING_KIND; NULL otherwise
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    services: Mapped[list["Service"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )

    def mark_hosting(self) -> None:
        """This nginx now hosts sites (``/apps/{id}/sites``)."""
        self.kind = HOSTING_KIND


class AppRevision(Base):
    __tablename__ = "app_revision"
    __table_args__ = (UniqueConstraint("app_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    number: Mapped[int]
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON)  # secrets excluded
    compose_yaml: Mapped[str] = mapped_column(Text)  # exact artefact applied
    # Template version it was compiled from (restoring recompiles with it); None: older rows.
    template_version_id: Mapped[int | None] = mapped_column(ForeignKey("template_version.id"))
    overrides: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # advanced settings
    # Compose written by hand (admin): applied as is, the form no longer drives it.
    custom_compose: Mapped[bool] = mapped_column(default=False, server_default="0")
    diff_from_previous: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[RevisionStatus] = mapped_column(
        str_enum(RevisionStatus), default=RevisionStatus.PENDING
    )


class Service(Base):
    """A logical container of the stack, as described by the current revision."""

    __tablename__ = "service"
    __table_args__ = (UniqueConstraint("app_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(63))
    image: Mapped[str] = mapped_column(String(500))
    image_digest: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[ServiceRole] = mapped_column(str_enum(ServiceRole))
    restart_policy: Mapped[str] = mapped_column(String(20))
    cpu_limit: Mapped[float | None]
    mem_limit: Mapped[int | None]

    ports: Mapped[list["PortBinding"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )
    volumes: Mapped[list["VolumeMount"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )


class PortBinding(Base):
    __tablename__ = "port_binding"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("service.id", ondelete="CASCADE"))
    host_ip: Mapped[str | None] = mapped_column(String(45))
    host_port: Mapped[int | None]
    container_port: Mapped[int]
    protocol: Mapped[str] = mapped_column(String(3))
    purpose: Mapped[str] = mapped_column(String(10))
    exposure: Mapped[Exposure] = mapped_column(str_enum(Exposure))


class VolumeMount(Base):
    __tablename__ = "volume_mount"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("service.id", ondelete="CASCADE"))
    kind: Mapped[VolumeKind] = mapped_column(str_enum(VolumeKind))
    source: Mapped[str] = mapped_column(String(1000))
    target: Mapped[str] = mapped_column(String(1000))
    read_only: Mapped[bool] = mapped_column(default=False)
    backup: Mapped[bool] = mapped_column(default=False)
    owner: Mapped[str | None] = mapped_column(String(21))  # "uid:gid", None: PUID/PGID


class AppSecret(Base):
    """A form secret, AES-GCM encrypted and bound to ``app:<id>:<key>``."""

    __tablename__ = "secret"
    __table_args__ = (UniqueConstraint("app_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(63))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)


class AppDependency(Base):
    """An app of a zone starts after another one of the same zone (``depends_on_id``), and
    stops before it. Both in the same zone: checked by the service, and the dependencies of
    an app that changes zone are removed with the move."""

    __tablename__ = "app_dependency"
    __table_args__ = (CheckConstraint("app_id != depends_on_id", name="not_self"),)

    app_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), primary_key=True, index=True
    )
