"""The addressing rules, as pure functions (no database, no Docker): which networks are
free, the next /24 for a zone, the next /28 for an app, the next address in a network, and
the checks every subnet or address chosen by hand goes through."""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

from hivora.core.errors import ConflictError, ValidationError

Net = ipaddress.IPv4Network

# The Hivora range is picked among these /16 (10.100.0.0/16 to 10.250.0.0/16).
RANGE_CANDIDATES = tuple(f"10.{n}.0.0/16" for n in range(100, 251))
ZONE_PREFIX = 24
APP_PREFIX = 28  # an app's own network: 13 addresses (gateway .1, services from .2)
FIRST_HOST = 10  # in a zone's network, apps start at .10 (.2 to .9 kept for a hand choice)
ZONE_PREFIX_RANGE = (16, 27)  # a zone's subnet chosen by hand


class SubnetOverlapError(ConflictError):
    code = "subnet_overlap"


class AddressTakenError(ConflictError):
    code = "ip_taken"


class NetworkFullError(ConflictError):
    code = "network_full"


class SubnetInvalidError(ValidationError):
    code = "subnet_invalid"


class AddressInvalidError(ValidationError):
    code = "ip_invalid"


@dataclass(frozen=True, slots=True)
class Taken:
    """A network already used, and what uses it (shown when a choice overlaps it)."""

    network: str
    owner: str


def net(value: str) -> Net:
    """An IPv4 network in CIDR form (host bits refused)."""
    try:
        parsed = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError as exc:
        raise SubnetInvalidError("not a network in CIDR form", subnet=value) from exc
    if not isinstance(parsed, ipaddress.IPv4Network):
        raise SubnetInvalidError("IPv4 only", subnet=value)
    return parsed


def overlap(candidate: Net, taken: Iterable[Taken]) -> Taken | None:
    """The first taken network the candidate overlaps, if any."""
    for t in taken:
        try:
            other = ipaddress.ip_network(t.network, strict=False)
        except ValueError:
            continue
        if other.version == 4 and candidate.overlaps(other):
            return t
    return None


def check_subnet(value: str, taken: Iterable[Taken],
                 prefixes: tuple[int, int] = ZONE_PREFIX_RANGE) -> Net:  # fmt: skip
    """A subnet chosen by hand: private, a sensible size, overlapping nothing taken."""
    candidate = net(value)
    if not candidate.is_private or candidate.is_loopback or candidate.is_link_local:
        raise SubnetInvalidError("a private network only (10/8, 172.16/12, 192.168/16)",
                                 subnet=value)  # fmt: skip
    low, high = prefixes
    if not low <= candidate.prefixlen <= high:
        raise SubnetInvalidError(f"from /{low} to /{high}", subnet=value, low=low, high=high)
    if hit := overlap(candidate, taken):
        raise SubnetOverlapError("this network overlaps another one", subnet=value,
                                 network=hit.network, owner=hit.owner)  # fmt: skip
    return candidate


def free_subnet(within: Iterable[Net], prefix: int, taken: Iterable[Taken]) -> Net | None:
    """The first /prefix inside ``within`` (in order) that overlaps nothing taken."""
    used = list(taken)
    for block in within:
        if block.prefixlen > prefix:
            continue
        for candidate in block.subnets(new_prefix=prefix):
            if overlap(candidate, used) is None:
                return candidate
    return None


def pick_range(taken: Iterable[Taken]) -> Net:
    """The Hivora range: the first candidate /16 that overlaps nothing taken."""
    used = list(taken)
    for value in RANGE_CANDIDATES:
        candidate = net(value)  # IPv4 by construction
        if overlap(candidate, used) is None:
            return candidate
    raise NetworkFullError("no free /16 in 10.100.0.0 to 10.250.0.0 for Hivora's networks")


def zones_half(hivora_range: Net) -> Net:
    """The lower half of the range: the zones' /24."""
    return next(hivora_range.subnets(prefixlen_diff=1))


def apps_half(hivora_range: Net) -> Net:
    """The upper half of the range: the /28 of the apps' own networks."""
    return list(hivora_range.subnets(prefixlen_diff=1))[1]


def next_to(vpn_subnet: str, taken: Iterable[Taken]) -> Net:
    """A /24 for a zone a VPN reaches: the first free one after the VPN's network
    (10.8.0.0/24 -> 10.8.1.0/24, then 10.8.2.0/24...), private."""
    used = list(taken)
    start = (int(net(vpn_subnet).broadcast_address) // 256 + 1) * 256
    for k in range(256):
        candidate = ipaddress.IPv4Network((start + k * 256, ZONE_PREFIX))
        if not candidate.is_private:
            break
        if overlap(candidate, used) is None:
            return candidate
    raise NetworkFullError("no free network next to the VPN's for this zone", vpn=vpn_subnet)


def reserved(network: Net) -> set[str]:
    """Addresses never given to a container: the network's own, its gateway, broadcast."""
    return {str(network.network_address), str(network.network_address + 1),
            str(network.broadcast_address)}  # fmt: skip


def free_address(network: Net, used: Iterable[str], first: int = 2) -> str:
    """The first address from ``.first`` on, not reserved nor used."""
    taken = reserved(network) | set(used)
    for host in network.hosts():
        if int(host) - int(network.network_address) < first:
            continue
        if str(host) not in taken:
            return str(host)
    raise NetworkFullError("no free address left in this network", network=str(network))


def check_address(value: str, network: Net, used: dict[str, str]) -> str:
    """An address chosen by hand: in the network, not reserved, free (``used``: address ->
    what has it)."""
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise AddressInvalidError("not an IPv4 address", ip=value) from exc
    if address not in network:
        raise AddressInvalidError("outside the network", ip=value, network=str(network))
    if str(address) in reserved(network):
        raise AddressInvalidError("the network's own address, its gateway or broadcast",
                                  ip=value, network=str(network))  # fmt: skip
    if owner := used.get(str(address)):
        raise AddressTakenError("this address is already given", ip=value, owner=owner)
    return str(address)
