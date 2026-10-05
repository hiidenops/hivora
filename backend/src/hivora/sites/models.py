"""The sites an nginx app hosts: its main site (the "html" volume, on the app's web port)
and the added ones (a folder of the "sites" volume, each on its own port)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime


class Site(Base):
    __tablename__ = "site"
    __table_args__ = (
        # Explicit names: the convention names a unique constraint after its first
        # column, and all three start with app_id.
        UniqueConstraint("app_id", "slug", name="uq_site_app_id_slug"),
        UniqueConstraint("app_id", "root", name="uq_site_app_id_root"),  # one main site
        UniqueConstraint("app_id", "port", name="uq_site_app_id_port"),
        # The main site (root "") has no port of its own: it is the app's web port.
        CheckConstraint(
            "(root = '' AND port IS NULL) OR (root != '' AND port IS NOT NULL)",
            name="main_iff_no_port",
        ),
        CheckConstraint("port IS NULL OR port BETWEEN 1 AND 65535", name="port_range"),
        CheckConstraint("root = '' OR root = slug", name="root_is_slug"),
        CheckConstraint("slug != ''", name="slug_not_empty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(63))  # "main" for the main site; never changes
    name: Mapped[str] = mapped_column(String(100))
    root: Mapped[str] = mapped_column(String(63))  # "": the html volume; else sites/<root>
    port: Mapped[int | None]  # None: the main site, on the app's web port
    server_name: Mapped[str | None] = mapped_column(String(253))  # None: any ("_")
    enabled: Mapped[bool] = mapped_column(default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
