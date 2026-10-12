"""The host's HIVORA-BLOCK chain, rendered from the blocked addresses: pure, no I/O.

The chain is called first from INPUT (the host's services) and DOCKER-USER (the apps Docker
publishes: their packets are forwarded, and keep the client's address after Docker's NAT).
``restore_text`` is the whole input of ``iptables-restore --noflush`` (or ``ip6tables-…``):
declaring the chain empties it (or creates it), and touches no other chain, so the rules
change at once. Only canonical addresses validated here are ever written.
"""

import ipaddress
from collections.abc import Iterable
from typing import Literal

from hivora.core.errors import ValidationError

CHAIN = "HIVORA-BLOCK"
Family = Literal[4, 6]


class InvalidAddressError(ValidationError):
    code = "invalid_address"


def valid_address(text: str) -> str:
    """One IP address in its canonical form (an IPv4 seen through IPv6 as IPv4); a network,
    a scoped IPv6, the unspecified address, loopback, multicast or anything else is refused."""
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        raise InvalidAddressError("not an IP address", field="address") from None
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.scope_id:  # "fe80::1%eth0": an interface, not a source address
            raise InvalidAddressError("not an IP address", field="address")
        addr = addr.ipv4_mapped or addr
    if addr.is_unspecified or addr.is_loopback or addr.is_multicast:
        raise InvalidAddressError("this address cannot be blocked", field="address")
    return str(addr)


def split(addresses: Iterable[str]) -> dict[Family, list[str]]:
    """The valid addresses per family, sorted, without duplicates."""
    found = {ipaddress.ip_address(valid_address(text)) for text in addresses}
    v4 = sorted(a for a in found if isinstance(a, ipaddress.IPv4Address))
    v6 = sorted(a for a in found if isinstance(a, ipaddress.IPv6Address))
    return {4: [str(a) for a in v4], 6: [str(a) for a in v6]}


def restore_text(addresses: Iterable[str], family: Family) -> str:
    """The chain, emptied then refilled: one DROP per address of this family."""
    prefix = 32 if family == 4 else 128
    rules = [f"-A {CHAIN} -s {a}/{prefix} -j DROP" for a in split(addresses)[family]]
    return "\n".join(["*filter", f":{CHAIN} - [0:0]", *rules, "COMMIT", ""])
