"""A VPN's own DNS: the CoreDNS of the WireGuard image, its Corefile written by Hivora.

Clients get the VPN server as their DNS: it answers the names declared for the VPN
(an IP, or an app's container through Docker's DNS) and forwards everything else, so
the web keeps working. Pure: no database, no Docker.
"""

import ipaddress
import re
from dataclasses import dataclass

from hivora.core.errors import ValidationError

LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
NAME = re.compile(rf"^(?=.{{1,253}}$)({LABEL}\.)+[a-z]([a-z0-9-]{{0,61}}[a-z0-9])?$")
DOCKER_DNS = "127.0.0.11"  # Docker's embedded resolver: containers by name, the host's DNS


class DnsNameError(ValidationError):
    code = "vpn_dns_bad_name"


@dataclass(frozen=True, slots=True)
class Record:
    name: str
    ip: str | None = None
    container: str | None = None  # Docker name of the target container


def check_name(name: str) -> str:
    name = name.strip().lower().rstrip(".")
    if not NAME.fullmatch(name):
        raise DnsNameError("invalid domain name (e.g. nas.lan)", field="name")
    return name


def upstream(dns: str) -> str:
    """The VPN's DNS setting (IPs, comma-separated) or, empty, the host's (through Docker)."""
    ips = []
    for part in dns.replace(" ", "").split(","):
        try:
            ips.append(str(ipaddress.ip_address(part)))
        except ValueError:
            continue
    return " ".join(ips) or "/etc/resolv.conf"


def corefile(records: list[Record], dns: str) -> str:
    ips = [f"        {r.ip} {r.name}" for r in records if r.ip]
    hosts = ["    hosts {", "        ttl 30", *ips, "        fallthrough", "    }"]
    apps = [r for r in records if r.container]
    lines = [
        "# Written by Hivora: edits here are replaced on the next change.",
        ". {", "    errors", "    health", "    loop", *hosts,
        f"    forward . {upstream(dns)}", "    cache 30", "}",
    ]  # fmt: skip
    if apps:  # one block for the apps' names: rewritten to the container's, Docker answers
        lines += ["", " ".join(f"{r.name}." for r in apps) + " {", "    errors"]
        for r in apps:
            lines += [f"    rewrite continue name exact {r.name}. {r.container}. answer auto",
                      f"    rewrite ttl exact {r.name}. 30"]  # fmt: skip
        # CoreDNS sends a name to the block of its longest zone: under an app's name
        # (web.home.lan under home.lan), an IP's name lands here, so this block knows them
        # too (rewrite runs before hosts: an IP's name passes it untouched).
        if ips:
            lines += hosts
        lines += [f"    forward . {DOCKER_DNS}", "}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    assert check_name(" MC.Local. ") == "mc.local"
    for bad in ("local", "a b.local", "x;y.local", "-a.local", "a.1"):
        try:
            check_name(bad)
            raise AssertionError(bad)
        except DnsNameError:
            pass
    assert upstream("1.1.1.1, 9.9.9.9") == "1.1.1.1 9.9.9.9"
    assert upstream("") == "/etc/resolv.conf"
    text = corefile([Record("nas.local", ip="192.168.1.20"),
                     Record("mc.local", container="mc-server-1")], "")  # fmt: skip
    assert "192.168.1.20 nas.local" in text and "mc.local. {" in text
    assert "name exact mc.local. mc-server-1. answer auto" in text
    # An IP's name under an app's: known by the app's block too (its longest zone).
    text = corefile([Record("home.lan", container="web-1"),
                     Record("web.home.lan", ip="10.8.1.5")], "")  # fmt: skip
    assert text.split("home.lan. {")[1].count("10.8.1.5 web.home.lan") == 1
