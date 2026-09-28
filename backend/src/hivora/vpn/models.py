"""WireGuard peers of a managed VPN: the server itself and its clients."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base


class VpnPeer(Base):
    """Private keys are AES-GCM encrypted, bound to ``vpn:<app_id>:<public key>``."""

    __tablename__ = "vpn_peer"
    __table_args__ = (UniqueConstraint("app_id", "address"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    server: Mapped[bool] = mapped_column(default=False)  # the VPN's own key pair
    name: Mapped[str] = mapped_column(String(32))
    address: Mapped[str] = mapped_column(String(45))
    enabled: Mapped[bool] = mapped_column(default=True)
    allowed_ips: Mapped[list[Any] | None] = mapped_column(JSON)  # None: the VPN's default
    public_key: Mapped[str] = mapped_column(String(44))
    private_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    private_key: Mapped[bytes] = mapped_column(LargeBinary)
