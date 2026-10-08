"""A VPN app's addressing: its settings, network, addresses and the routes a client gets.

Pure: no database, no Docker. `VpnApp` is what the tools know of one VPN app.
"""

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hivora.core.errors import ConflictError, ValidationError
from hivora.docker_gateway import ContainerInfo
from hivora.templates.schema import Vpn
from hivora.vpn import wireguard as wg


class VpnFullError(ConflictError):
    code = "vpn_full"


class VpnNetworkError(ValidationError):
    code = "vpn_bad_network"


class VpnAddressError(ValidationError):
    code = "vpn_bad_address"


@dataclass(frozen=True, slots=True)
class VpnApp:
    app_id: int
    slug: str
    spec: Vpn
    container: ContainerInfo | None
    values: dict[str, Any]
    host_config: Path  # the server config on the host
    config: str  # the same file inside the container
    host_acl: Path  # the access-rights script on the host
    acl: str  # the same file inside the container

    @property
    def zones(self) -> list[str]:
        return [z for z in str(self.values.get(self.spec.zones_field or "") or "").split(",") if z]

    def value(self, field: str | None, default: str = "") -> str:
        return str(self.values.get(field or "") or default)

    def network(self) -> tuple[str, str]:
        """(subnet, server address) from the advanced settings, validated."""
        s = self.spec
        try:
            net, server = wg.network(self.value(s.subnet_field, s.subnet),
                                     self.value(s.server_ip_field))  # fmt: skip
        except ValueError as exc:
            raise VpnNetworkError(f"invalid VPN addressing: {exc}") from None
        return str(net), server

    @property
    def endpoint_port(self) -> str:
        return self.value(self.spec.port_field, str(self.spec.port))

    @property
    def endpoint(self) -> str:
        """host:port clients connect to (brackets around an IPv6 host)."""
        host = self.value(self.spec.endpoint_field)
        port = self.endpoint_port
        return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"

    @property
    def default_allowed_ips(self) -> str:
        return self.value(self.spec.allowed_ips_field, "0.0.0.0/0")


def check_address(vpn: VpnApp, address: str, taken: set[str]) -> None:
    subnet, _ = vpn.network()
    try:
        ok = ipaddress.ip_address(address) in set(ipaddress.ip_network(subnet).hosts())
    except ValueError:
        ok = False
    if not ok or address in taken:
        raise VpnAddressError("address outside the VPN network or already used",
                              field="address", address=address[:45])  # fmt: skip


def zone_networks(zones: list[str]) -> dict[str, str]:
    """Docker network name -> zone slug or "@<app>", for the networks a VPN reaches."""
    return {(f"{z[1:]}_default" if z.startswith("@") else f"hivora-zone-{z}"): z for z in zones}


def allowed_ips(vpn: VpnApp, routing: str, custom: list[str] | None,
                access: wg.Access | None) -> str:  # fmt: skip
    """What a client routes through the tunnel (its config's AllowedIPs)."""
    default = vpn.default_allowed_ips
    if routing == "all":
        return "0.0.0.0/0"
    if routing == "access" and access is not None:
        return ", ".join(wg.routes(vpn.network()[0], access))
    if routing == "custom":
        return ", ".join(custom or []) or default
    return default
