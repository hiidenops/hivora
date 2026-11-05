"""The addressing plan (intention): fixed addresses of containers, fixed networks of apps.
Docker holds what is really applied; the Addressing page shows the gap."""

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base


class IpAssignment(Base):
    """A container's fixed address in one Docker network (a zone's, an app's own, or one
    it joins). Keyed by the app's slug: the plan is made before the app's row exists."""

    __tablename__ = "ip_assignment"
    __table_args__ = (
        UniqueConstraint("network", "address", name="uq_ip_assignment_address"),
        UniqueConstraint("network", "app", "service", name="uq_ip_assignment_service"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    network: Mapped[str] = mapped_column(String(128))  # Docker network name
    app: Mapped[str] = mapped_column(String(63), index=True)  # app slug
    service: Mapped[str] = mapped_column(String(63))
    address: Mapped[str] = mapped_column(String(15))
    manual: Mapped[bool] = mapped_column(default=False)  # chosen by hand (kept on renumbering)


class AppNetwork(Base):
    """An app's own network (``<slug>_default``): its fixed subnet."""

    __tablename__ = "app_network"

    app: Mapped[str] = mapped_column(String(63), primary_key=True)  # app slug
    subnet: Mapped[str] = mapped_column(String(18), unique=True)
