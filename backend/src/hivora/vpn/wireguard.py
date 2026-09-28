"""Plain WireGuard: key pairs, server/client configurations, `wg show dump` parsing.

Hivora is the source of truth: it rewrites the server's wg0.conf from its
database and applies it live (`wg syncconf`), so no API or web UI is needed.
"""

import base64
import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

# NAT on every interface: clients reach the LAN and the zone networks the
# container joins. Kept in the config so every restart restores it.
NAT = "iptables -t nat {op} POSTROUTING -s {subnet} -j MASQUERADE"
PRIVATE = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")  # "local network" for access rights
CHAIN = "HIVORA-VPN"


def keypair() -> tuple[str, str]:
    """(private, public), base64 as `wg genkey | wg pubkey` prints them."""
    key = X25519PrivateKey.generate()
    return (base64.b64encode(key.private_bytes_raw()).decode(),
            base64.b64encode(key.public_key().public_bytes_raw()).decode())  # fmt: skip


def public_of(private: str) -> str:
    key = X25519PrivateKey.from_private_bytes(base64.b64decode(private))
    return base64.b64encode(key.public_key().public_bytes_raw()).decode()


@dataclass(frozen=True, slots=True)
class Peer:
    name: str
    address: str  # e.g. 10.8.0.2
    public_key: str


def network(subnet: str, server_ip: str = "") -> tuple[ipaddress.IPv4Network, str]:
    """The VPN network and the server's address in it (default: its first address).

    Raises ValueError when the network or the address is unusable.
    """
    net = ipaddress.ip_network(subnet, strict=True)
    if not isinstance(net, ipaddress.IPv4Network) or net.prefixlen > 30:
        raise ValueError("an IPv4 network of at least 4 addresses is needed")
    server = ipaddress.ip_address(server_ip) if server_ip else next(net.hosts())
    if server not in set(net.hosts()):
        raise ValueError("the server address is not a host of the VPN network")
    return net, str(server)


def free_address(subnet: str, used: set[str]) -> str | None:
    hosts = ipaddress.ip_network(subnet).hosts()
    return next((str(ip) for ip in hosts if str(ip) not in used), None)


def server_conf(private: str, subnet: str, address: str, port: int, iface: str,
                peers: list[Peer], acl: str) -> str:  # fmt: skip
    """``acl``: path (in the container) of the access-rights script run on PostUp."""
    prefix = ipaddress.ip_network(subnet).prefixlen
    lines = [
        "# Written by Hivora: edits here are replaced on the next change.",
        "[Interface]",
        f"Address = {address}/{prefix}",
        f"ListenPort = {port}",
        f"PrivateKey = {private}",
        f"PostUp = {NAT.format(op='-A', subnet=subnet)}; sh {acl}",
        f"PostDown = {NAT.format(op='-D', subnet=subnet)}; iptables -D FORWARD -i {iface}"
        f" -j {CHAIN}; iptables -F {CHAIN}; iptables -X {CHAIN}",
    ]
    for p in peers:
        lines += ["", f"# {p.name}", "[Peer]", f"PublicKey = {p.public_key}",
                  f"AllowedIPs = {p.address}/32"]  # fmt: skip
    return "\n".join(lines) + "\n"


def client_conf(private: str, address: str, dns: str, server_public: str, endpoint: str,
                allowed_ips: str) -> str:  # fmt: skip
    lines = ["[Interface]", f"PrivateKey = {private}", f"Address = {address}/32"]
    if dns:
        lines.append(f"DNS = {dns}")
    lines += ["", "[Peer]", f"PublicKey = {server_public}", f"AllowedIPs = {allowed_ips}",
              f"Endpoint = {endpoint}", "PersistentKeepalive = 25"]  # fmt: skip
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class Access:
    """What one client may reach, enforced in the container's FORWARD chain."""

    address: str
    internet: bool
    lan: bool
    zones: tuple[str, ...]  # subnets of the zones it may reach


def acl_script(iface: str, clients: list[Access], zone_subnets: list[str]) -> str:
    """Rebuild the access chain aside, then swap it in: never a moment without rules.

    Per client, first match wins: allowed zones, other zones dropped, local network,
    then the Internet. Unknown sources (should not exist) are dropped.
    """
    new = "HIVORA-VPN-NEW"
    lines = ["#!/bin/sh", "# Written by Hivora: VPN clients' access rights.", "set -e",
             f"iptables -N {new} 2>/dev/null || iptables -F {new}"]  # fmt: skip
    for c in clients:
        rule = f"iptables -A {new} -s {c.address}/32"
        lines += [f"{rule} -d {n} -j ACCEPT" for n in c.zones]
        lines += [f"{rule} -d {n} -j DROP" for n in zone_subnets if n not in c.zones]
        verdict = "ACCEPT" if c.lan else "DROP"
        lines += [f"{rule} -d {n} -j {verdict}" for n in PRIVATE]
        lines.append(f"{rule} -j {'ACCEPT' if c.internet else 'DROP'}")
    lines += [
        f"iptables -A {new} -j DROP",
        f"iptables -I FORWARD 1 -i {iface} -j {new}",
        f"iptables -D FORWARD -i {iface} -j {CHAIN} 2>/dev/null || true",
        f"iptables -F {CHAIN} 2>/dev/null || true",
        f"iptables -X {CHAIN} 2>/dev/null || true",
        f"iptables -E {new} {CHAIN}",
    ]
    return "\n".join(lines) + "\n"


def routes(vpn_subnet: str, access: Access) -> list[str]:
    """Traffic sent through the tunnel when only what the client may reach goes there."""
    if access.internet:
        return ["0.0.0.0/0"]
    return [vpn_subnet, *(PRIVATE if access.lan else access.zones)]


@dataclass(frozen=True, slots=True)
class PeerStats:
    latest_handshake: str | None  # ISO 8601
    rx: int
    tx: int
    endpoint: str | None = None  # where the client connects from (ip:port)
    online: bool = False  # handshake in the last 3 minutes


def parse_dump(text: str, now: float) -> dict[str, PeerStats]:
    """`wg show <iface> dump`: an interface line, then one tab-separated line per peer."""
    out = {}
    for line in text.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 7 or not f[4].isdigit():
            continue
        seen = int(f[4])
        when = datetime.fromtimestamp(seen, UTC).isoformat() if seen else None
        endpoint = None if f[2] == "(none)" else f[2]
        out[f[0]] = PeerStats(when, int(f[5]), int(f[6]), endpoint, bool(seen) and now - seen < 180)
    return out
