"""Persisted template versions: immutable, referenced by the apps deployed from them."""

from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime


class TemplateVersion(Base):
    __tablename__ = "template_version"
    __table_args__ = (UniqueConstraint("source", "slug", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(63))
    version: Mapped[str] = mapped_column(String(50))
    api_version: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    manifest: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
