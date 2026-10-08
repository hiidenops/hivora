"""Putting a VPN's configuration in place: files in the app's volume, applied by exec.

What Docker is asked (the zones' networks, `wg-quick` / `wg syncconf` in the container)
and what is written on the host (wg0.conf, the access-rights script).
"""

import ipaddress
import os
from contextlib import suppress

from hivora.core.errors import ConflictError
from hivora.docker_gateway import DockerGateway
from hivora.vpn.addressing import VpnApp, zone_networks


class VpnApplyError(ConflictError):
    code = "vpn_apply_failed"


async def zone_subnets(gateway: DockerGateway, vpn: VpnApp) -> dict[str, tuple[str, ...]]:
    """Subnets of the networks this VPN reaches, by zone slug or "@<app>"."""
    if not vpn.zones:
        return {}
    names = zone_networks(vpn.zones)
    return {names[n.name]: n.subnets for n in await gateway.list_networks()
            if n.name in names}  # fmt: skip


def write_files(vpn: VpnApp, text: str, acl: str, *, if_changed: bool) -> bool:
    """Write wg0.conf and the access script; False when ``if_changed`` and both are as is."""
    with suppress(OSError):
        if if_changed and vpn.host_config.read_text() == text \
                and vpn.host_acl.read_text() == acl:  # fmt: skip
            return False
    vpn.host_config.parent.mkdir(parents=True, exist_ok=True)
    for path, content in ((vpn.host_acl, acl), (vpn.host_config, text)):
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # private key inside
        with os.fdopen(fd, "w") as f:
            f.write(content)
        tmp.replace(path)
    return True


async def bring_up(gateway: DockerGateway, vpn: VpnApp, address: str) -> None:
    assert vpn.container is not None
    s = vpn.spec
    subnet, _ = vpn.network()
    # Same address: peers and rights applied live. New addressing: interface rebuilt.
    # ponytail: the old network's NAT rule stays until the container restarts (harmless)
    i, c = s.interface, vpn.config
    inet = f"inet {address}/{ipaddress.ip_network(subnet).prefixlen} "
    code, out = await gateway.exec_run(vpn.container.id, ["sh", "-c", (
        f"if wg show {i} >/dev/null 2>&1; then"
        f" if ip -4 -o addr show {i} | grep -qF '{inet}'; then"
        f" wg-quick strip {c} > /tmp/{i}.conf && wg syncconf {i} /tmp/{i}.conf"
        f" && sh {vpn.acl};"
        f" else ip link del {i} && wg-quick up {c}; fi;"
        f" else wg-quick up {c}; fi"
    )])  # fmt: skip
    if code != 0:
        raise VpnApplyError("WireGuard refused the configuration", output=out[-500:])
