"""The host's firewall intentions, each applied to the host by a job and again whenever
Hivora starts: the blocked addresses (the HIVORA-BLOCK chain, hostfw.blocklist) and the
static IPv4 routes (marked proto 241, hostfw.routing)."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime


class BlockedAddress(Base):
    __tablename__ = "blocked_address"
    # The address's form (one IP, canonical) is checked by hostfw.blocklist.valid_address:
    # SQLite has no regular expressions in a constraint.
    __table_args__ = (CheckConstraint("address != ''", name="address_not_empty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String(45), unique=True)  # one IP, canonical form
    note: Mapped[str | None] = mapped_column(String(200))  # e.g. where it was seen
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StaticRoute(Base):
    __tablename__ = "static_route"
    # The forms (a canonical IPv4 network, an IPv4 gateway, an interface name) are checked by
    # hostfw.routing: SQLite has no regular expressions in a constraint.
    __table_args__ = (
        CheckConstraint("destination != '' AND gateway != ''", name="not_empty"),
        CheckConstraint("metric IS NULL OR metric BETWEEN 0 AND 4294967295", name="metric_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    destination: Mapped[str] = mapped_column(String(18), unique=True)  # e.g. 10.8.0.0/24
    gateway: Mapped[str] = mapped_column(String(15))
    dev: Mapped[str | None] = mapped_column(String(15))  # None: the kernel picks it
    metric: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
