"""A VPN client's rights: what it reaches, whether it is active, the fields the API changes.

Pure: no database, no Docker (the zones' subnets are read by the caller).
"""

from datetime import UTC, datetime
from typing import Any

from hivora.vpn import wireguard as wg
from hivora.vpn.addressing import VpnApp
from hivora.vpn.models import VpnPeer

ROUTINGS = ("default", "all", "access", "custom")


def access_of(peer: VpnPeer, vpn: VpnApp, subnets: dict[str, tuple[str, ...]]) -> wg.Access:
    a = peer.access or {"internet": True, "lan": True, "zones": vpn.zones}
    zones = [z for z in a.get("zones") or [] if z in vpn.zones]
    return wg.Access(peer.address, bool(a.get("internet")), bool(a.get("lan")),
                     tuple(n for z in zones for n in subnets.get(z, ())))  # fmt: skip


def is_active(peer: VpnPeer, now: datetime) -> bool:
    return peer.enabled and (peer.expires_at is None or peer.expires_at > now)


def client_out(c: VpnPeer, vpn: VpnApp, st: wg.PeerStats, now: datetime) -> dict[str, Any]:
    a = access_of(c, vpn, {})
    zones = [z for z in (c.access or {"zones": vpn.zones}).get("zones") or [] if z in vpn.zones]
    return {
        "id": c.id, "name": c.name, "address": c.address, "enabled": c.enabled,
        "active": is_active(c, now), "expires_at": c.expires_at,
        "access": {"internet": a.internet, "lan": a.lan, "zones": zones},
        "routing": c.routing, "allowed_ips": c.allowed_ips, "public_key": c.public_key,
        "latest_handshake": st.latest_handshake, "online": st.online,
        "endpoint": st.endpoint, "rx": st.rx, "tx": st.tx,
    }  # fmt: skip


def apply_changes(peer: VpnPeer, changes: dict[str, Any], now: datetime) -> None:
    """Fields sent by the API (only those present change)."""
    if "name" in changes:
        peer.name = changes["name"]
    if "access" in changes:
        peer.access = changes["access"]
    if "expires_at" in changes:
        at = changes["expires_at"]
        peer.expires_at = at.replace(tzinfo=UTC) if at and at.tzinfo is None else at
    if "routing" in changes:
        peer.routing = changes["routing"]
    if changes.get("allowed_ips"):
        peer.allowed_ips, peer.routing = changes["allowed_ips"], "custom"
    if changes.get("clear_allowed_ips"):
        peer.allowed_ips, peer.routing = None, "default"
    if changes.get("enabled") is not None:
        peer.enabled = changes["enabled"]
        if peer.enabled and not is_active(peer, now):
            peer.expires_at = None  # re-enabled by hand after expiring
