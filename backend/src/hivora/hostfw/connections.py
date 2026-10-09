"""Who is connected to the host right now: one row per remote address.

Two sources, both read only through the host agent's fixed command lines: the host's
own sockets (``ss``: SSH and the other host services) and the kernel's connection
tracking (``conntrack``: Docker publishes the apps' ports by NAT, so their connections
never show in ``ss``). Only inbound connections count: to a port the host listens on,
or to a port Docker publishes. ``conntrack`` comes from the host (``apt install
conntrack``); without it only the host's own services are seen.
"""

import ipaddress
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from hivora.hostfw.service import HostFirewall, parse_ss

SS_ESTABLISHED = ["ss", "-H", "-tnp", "state", "established"]
SS_LISTENING = ["ss", "-H", "-tulpn"]
CONNTRACK = ["conntrack", "-L", "-p", "tcp", "--state", "ESTABLISHED"]
MAX_ROWS = 500

_ADDR = re.compile(r"^\[?(.+?)\]?:(\d+)$")
_PROCESS = re.compile(r'users:\(\("([^"]+)"')
_FIELD = re.compile(r"(src|dst|sport|dport)=(\S+)")


@dataclass(frozen=True, slots=True)
class Flow:
    """One inbound TCP connection: from `remote` to the host's `port`."""

    remote: str
    port: int
    process: str = ""  # the host process holding it (``ss``), if known


def _address(text: str) -> tuple[str, int] | None:
    m = _ADDR.match(text)
    if not m:
        return None
    host = m.group(1).removeprefix("::ffff:")  # IPv4 seen through an IPv6 socket
    return host, int(m.group(2))


def parse_ss_established(text: str) -> list[tuple[int, Flow]]:
    """``ss -H -tnp state established``: (local port, flow) per connection.

    Lines: ``Recv-Q Send-Q Local:Port Peer:Port [users:(("name",pid=…))]``."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local, peer = _address(parts[2]), _address(parts[3])
        if local and peer:
            m = _PROCESS.search(line)
            out.append((local[1], Flow(peer[0], local[1], m.group(1) if m else "")))
    return out


def parse_conntrack(text: str) -> list[Flow]:
    """``conntrack -L -p tcp --state ESTABLISHED``: the original direction of each entry
    (``src`` the client, ``dport`` the host port it asked for). Summary lines skipped."""
    flows = []
    for line in text.splitlines():
        if not line.startswith("tcp"):
            continue
        first: dict[str, str] = {}
        for key, value in _FIELD.findall(line):
            first.setdefault(key, value)  # the reply direction repeats the keys: ignored
        if "src" in first and first.get("dport", "").isdigit():
            flows.append(Flow(first["src"], int(first["dport"])))
    return flows


# What counts as the local network (the rest is the Internet): RFC 1918, CGNAT (Tailscale,
# carriers), link-local, loopback, IPv6 unique local and link-local.
LOCAL = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16",
    "127.0.0.0/8", "fc00::/7", "fe80::/10", "::1/128",
))  # fmt: skip


def origin(ip: str) -> str:
    """The origin of an address: "lan" on the local network (LOCAL), else "internet"."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "internet"
    return "lan" if any(addr in net for net in LOCAL) else "internet"


def group(
    host_flows: list[tuple[int, Flow]], nat_flows: list[Flow], *, listening: set[int],
    published: dict[int, str], containers: set[str], seen: dict[str, float], now: float,
) -> list[dict[str, Any]]:  # fmt: skip
    """Inbound connections per remote address. ``seen`` (remote -> first seen) is updated:
    an address gone is forgotten, a new one starts now."""
    count: dict[tuple[str, int], int] = defaultdict(int)
    names: dict[tuple[str, int], str] = {}
    for local_port, f in host_flows:  # to a port the host listens on (not its own client sockets)
        if local_port in listening and not f.remote.startswith("127.") and f.remote != "::1":
            count[(f.remote, f.port)] += 1
            names[(f.remote, f.port)] = published.get(f.port) or f.process
    nat: dict[tuple[str, int], int] = defaultdict(int)
    for f in nat_flows:  # to an app's published port, not a container's own traffic
        if f.port in published and f.remote not in containers:
            nat[(f.remote, f.port)] += 1
    for key, n in nat.items():  # docker-proxy may show the same connection in ss: no double
        count[key] = max(count[key], n)
        names.setdefault(key, published[key[1]])
    by_ip: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for (ip, port), n in count.items():
        by_ip[ip].append((port, n))
    for ip in list(seen):
        if ip not in by_ip:
            del seen[ip]
    totals = {ip: sum(n for _, n in ports) for ip, ports in by_ip.items()}
    # The Internet first, then the busiest.
    order = sorted(by_ip, key=lambda ip: (origin(ip) != "internet", -totals[ip], ip))[:MAX_ROWS]
    rows = []
    for ip in order:
        seen.setdefault(ip, now)
        rows.append({
            "ip": ip, "origin": origin(ip), "connections": totals[ip], "first_seen": seen[ip],
            "targets": [{"port": p, "name": names.get((ip, p), "")} for p, _ in sorted(by_ip[ip])],
        })  # fmt: skip
    return rows


async def connections(fw: HostFirewall) -> dict[str, Any]:
    """The inbound connections now, and whether ``conntrack`` could be read (else the
    apps' connections are missing)."""
    _, established = await fw._run(SS_ESTABLISHED, check=False)
    _, listening_out = await fw._run(SS_LISTENING, check=False)
    code, tracked = await fw._run(CONNTRACK, check=False)
    published: dict[int, str] = {}
    containers: set[str] = set()
    for c in fw.store.containers():
        containers.update(c.ips)
        for p in c.ports:
            if p.host_port and p.protocol == "tcp":
                published[p.host_port] = c.labels.get("io.hivora.app") or c.name
    listening = {item.port for item in parse_ss(listening_out) if item.protocol == "tcp"}
    rows = group(parse_ss_established(established), parse_conntrack(tracked) if code == 0 else [],
                 listening=listening, published=published, containers=containers,
                 seen=fw.seen, now=time.time())  # fmt: skip
    return {"conntrack": code == 0, "connections": rows}
