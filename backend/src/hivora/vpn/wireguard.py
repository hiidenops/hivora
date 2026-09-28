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
NAT = (
    "iptables -t nat {op} POSTROUTING -s {subnet} -j MASQUERADE; "
    "iptables {op} FORWARD -i {iface} -j ACCEPT; iptables {op} FORWARD -o {iface} -j ACCEPT"
)


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
                peers: list[Peer]) -> str:  # fmt: skip
    prefix = ipaddress.ip_network(subnet).prefixlen
    lines = [
        "# Written by Hivora: edits here are replaced on the next change.",
        "[Interface]",
        f"Address = {address}/{prefix}",
        f"ListenPort = {port}",
        f"PrivateKey = {private}",
        f"PostUp = {NAT.format(op='-A', subnet=subnet, iface=iface)}",
        f"PostDown = {NAT.format(op='-D', subnet=subnet, iface=iface)}",
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
class PeerStats:
    latest_handshake: str | None  # ISO 8601
    rx: int
    tx: int


def parse_dump(text: str) -> dict[str, PeerStats]:
    """`wg show <iface> dump`: an interface line, then one tab-separated line per peer."""
    out = {}
    for line in text.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 7 or not f[4].isdigit():
            continue
        seen = int(f[4])
        when = datetime.fromtimestamp(seen, UTC).isoformat() if seen else None
        out[f[0]] = PeerStats(when, int(f[5]), int(f[6]))
    return out
