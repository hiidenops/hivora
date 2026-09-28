"""WireGuard peers of a managed VPN: the server itself and its clients."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hivora.db.base import Base, UTCDateTime


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
    allowed_ips: Mapped[list[Any] | None] = mapped_column(JSON)  # routing "custom" only
    # What the client reaches, enforced by the server: {"internet", "lan", "zones": [slugs]}.
    # None: everything the VPN reaches.
    access: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Traffic the client sends through the tunnel: "default" (VPN setting), "all",
    # "access" (only what it may reach, the rest goes direct), "custom" (allowed_ips).
    routing: Mapped[str] = mapped_column(String(10), default="default", server_default="default")
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # disabled after
    public_key: Mapped[str] = mapped_column(String(44))
    private_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    private_key: Mapped[bytes] = mapped_column(LargeBinary)
    # Preshared key (extra symmetric layer), sealed like the private key; clients only.
    psk_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    psk: Mapped[bytes | None] = mapped_column(LargeBinary)
