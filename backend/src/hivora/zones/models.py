"""Zones: logical groups of apps, optionally backed by a dedicated Docker network."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime, str_enum


class NetworkMode(StrEnum):
    NONE = "none"
    SHARED = "shared"
    ISOLATED = "isolated"
    CUSTOM = "custom"


class Zone(Base):
    __tablename__ = "zone"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(7))
    icon: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, default="")
    network_mode: Mapped[NetworkMode] = mapped_column(
        str_enum(NetworkMode), default=NetworkMode.NONE
    )
    docker_network_id: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(default=0)
    is_system: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
