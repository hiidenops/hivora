"""The host's static IPv4 routes: validation and the command lines, pure (no I/O).

Hivora marks its routes ``proto 241`` and only ever replaces or deletes routes so marked:
those of DHCP, the kernel, Docker or set by hand are never touched. A route that could cut
the host off is refused: the default route, a destination over a directly connected network
(the LAN, Docker's bridges) or holding the requester's own address, a gateway outside the
connected networks, an unknown interface.
"""

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from hivora.core.errors import ConflictError, ValidationError

PROTO = "241"  # Hivora's routes (a free routing protocol number)
IFNAME = re.compile(r"^[A-Za-z0-9_.@-]{1,15}$")
MAX_METRIC = 4294967295
IPv4 = ipaddress.IPv4Network


class InvalidRouteError(ValidationError):
    code = "invalid_route"


class RouteOverlapsConnectedError(ConflictError):
    code = "route_overlaps_connected"


class RouteContainsRequesterError(ConflictError):
    code = "route_contains_requester"


class GatewayNotConnectedError(ConflictError):
    code = "gateway_not_connected"


class UnknownInterfaceError(ConflictError):
    code = "unknown_interface"


@dataclass(frozen=True, slots=True)
class Route:
    destination: str  # canonical IPv4 network
    gateway: str
    dev: str | None = None
    metric: int | None = None


@dataclass(frozen=True, slots=True)
class Connected:
    """The host's directly connected networks and the interfaces it knows (``ip -j route``)."""

    networks: tuple[tuple[IPv4, str], ...]  # (network, interface)
    devs: frozenset[str]


def valid_destination(text: str) -> str:
    """An IPv4 network, canonical (``10.8.0.5/24`` -> ``10.8.0.0/24``; one address -> /32).
    Refused: the default route, IPv6, loopback, multicast, link-local, anything else."""
    try:
        net = ipaddress.ip_network(text, strict=False)
    except ValueError:
        raise InvalidRouteError("not an IPv4 network", field="destination") from None
    if not isinstance(net, IPv4) or net.prefixlen == 0:
        raise InvalidRouteError("not a routable IPv4 network", field="destination")
    if net.is_loopback or net.is_multicast or net.is_link_local or net.is_unspecified:
        raise InvalidRouteError("this network cannot be routed", field="destination")
    return str(net)


def valid_gateway(text: str) -> str:
    try:
        addr = ipaddress.IPv4Address(text)
    except ValueError:
        raise InvalidRouteError("not an IPv4 address", field="gateway") from None
    if addr.is_unspecified or addr.is_loopback or addr.is_multicast:
        raise InvalidRouteError("not a gateway address", field="gateway")
    return str(addr)


def valid_dev(text: str | None) -> str | None:
    if text in (None, ""):
        return None
    if not IFNAME.match(text):
        raise InvalidRouteError("not an interface name", field="dev")
    return text


def valid_metric(value: int | None) -> int | None:
    if value is not None and not 0 <= value <= MAX_METRIC:
        raise InvalidRouteError("metric out of range", field="metric")
    return value


def route(destination: str, gateway: str, dev: str | None = None,
          metric: int | None = None) -> Route:  # fmt: skip
    """A route of valid forms (its fit with the host: ``check``)."""
    return Route(valid_destination(destination), valid_gateway(gateway), valid_dev(dev),
                 valid_metric(metric))  # fmt: skip


def connected(rows: Iterable[dict[str, Any]]) -> Connected:
    """From ``ip -j route``: the networks reached without a gateway (scope link), and every
    interface a route names."""
    nets: list[tuple[IPv4, str]] = []
    devs: set[str] = set()
    for r in rows:
        dev = r.get("dev")
        if isinstance(dev, str):
            devs.add(dev)
        dst = r.get("dst")
        if dst == "default" or r.get("gateway") or r.get("scope") != "link" or not dev:
            continue
        try:
            net = ipaddress.ip_network(str(dst), strict=False)
        except ValueError:
            continue
        if isinstance(net, IPv4):
            nets.append((net, str(dev)))
    return Connected(tuple(nets), frozenset(devs))


def check(r: Route, host: Connected, *, requester: str | None) -> None:
    """Refuse a route that could cut the host off, or that the kernel would refuse."""
    dst = ipaddress.IPv4Network(r.destination)
    for net, _ in host.networks:
        if dst.overlaps(net):
            raise RouteOverlapsConnectedError(
                "over a directly connected network", destination=r.destination, network=str(net)
            )
    own = _ipv4(requester)
    if own is not None and own in dst:
        raise RouteContainsRequesterError("your own address is in this network",
                                          destination=r.destination)  # fmt: skip
    if r.dev is not None and r.dev not in host.devs:
        raise UnknownInterfaceError("no such interface on the host", dev=r.dev)
    gw = ipaddress.IPv4Address(r.gateway)
    if not any(gw in net and (r.dev is None or r.dev == dev) for net, dev in host.networks):
        raise GatewayNotConnectedError("the gateway is not on a connected network",
                                       gateway=r.gateway)  # fmt: skip


def plan(
    wanted: Iterable[Route], present: Iterable[dict[str, Any]]
) -> tuple[list[Route], list[str]]:
    """What to apply: every wanted route (``replace`` is idempotent), and the routes marked
    241 on the host that are no longer wanted (``present``: ``ip -j route show proto 241``)."""
    keep = sorted(wanted, key=lambda r: ipaddress.IPv4Network(r.destination))
    names = {r.destination for r in keep}
    found: set[IPv4] = set()
    for p in present:  # ip prints one address without its /32: made canonical first
        try:
            net = ipaddress.ip_network(str(p.get("dst")), strict=False)
        except ValueError:
            continue
        if isinstance(net, IPv4) and net.prefixlen:
            found.add(net)
    return keep, [str(n) for n in sorted(found) if str(n) not in names]


def replace_argv(r: Route) -> list[str]:
    argv = ["ip", "route", "replace", r.destination, "via", r.gateway]
    if r.dev:
        argv += ["dev", r.dev]
    if r.metric is not None:
        argv += ["metric", str(r.metric)]
    return [*argv, "proto", PROTO]


def delete_argv(destination: str) -> list[str]:
    return ["ip", "route", "del", valid_destination(destination), "proto", PROTO]


SHOW = ["ip", "-j", "route", "show", "proto", PROTO]
ALL = ["ip", "-j", "route"]


def _ipv4(text: str | None) -> ipaddress.IPv4Address | None:
    try:
        addr = ipaddress.ip_address(text or "")
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        return addr.ipv4_mapped
    return addr
