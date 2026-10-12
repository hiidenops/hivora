"""The addresses an admin blocked: the intention, applied to the host's HIVORA-BLOCK chain
by a job (hostfw.blocklist renders the rules), and again whenever Hivora starts."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
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
