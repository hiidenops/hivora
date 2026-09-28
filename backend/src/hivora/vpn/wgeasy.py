"""Minimal client for the wg-easy 15 HTTP API (Basic auth with the app's admin account)."""

import base64
from typing import Any

import aiohttp

from hivora.core.errors import HivoraError, NotFoundError

# NAT on every interface (not only eth0), so VPN clients also reach the zone
# networks the container joins. Same rules as wg-easy's default otherwise.
POST_UP = (
    "iptables -t nat -A POSTROUTING -s {{ipv4Cidr}} -j MASQUERADE; "
    "iptables -A INPUT -p udp -m udp --dport {{port}} -j ACCEPT; "
    "iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT"
)
POST_DOWN = POST_UP.replace(" -A ", " -D ")


# ClientUpdateSchema of wg-easy 15.4: every field is required (absent ones -> null).
UPDATE_FIELDS = (
    "name", "enabled", "expiresAt", "ipv4Address", "ipv6Address", "preUp", "postUp", "preDown",
    "postDown", "allowedIps", "serverAllowedIps", "firewallIps", "mtu", "jC", "jMin", "jMax",
    "i1", "i2", "i3", "i4", "i5", "persistentKeepalive", "serverEndpoint", "dns",
)  # fmt: skip


class VpnApiError(HivoraError):
    code = "vpn_unavailable"


class VpnClientNotFoundError(NotFoundError):
    code = "vpn_client_not_found"


class WgEasy:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/") + "/api"
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    async def _call(self, method: str, path: str, body: Any = None, raw: bool = False) -> Any:
        try:
            async with (
                aiohttp.ClientSession(
                    headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as http,
                http.request(method, self.base + path, json=body) as r,
            ):
                if r.status == 404:
                    raise VpnClientNotFoundError("no such VPN client")
                if r.status >= 400:
                    raise VpnApiError(f"wg-easy answered {r.status}", detail=(await r.text())[:200])
                if raw:
                    return await r.text()
                return await r.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise VpnApiError(f"wg-easy unreachable: {exc}") from exc

    async def clients(self) -> list[dict[str, Any]]:
        data = await self._call("GET", "/client")
        return data if isinstance(data, list) else []

    async def client(self, cid: int) -> dict[str, Any]:
        data: dict[str, Any] = await self._call("GET", f"/client/{cid}")
        return data

    async def create(self, name: str) -> int:
        return int(
            (await self._call("POST", "/client", {"name": name, "expiresAt": None}))["clientId"]
        )

    async def update(self, cid: int, **changes: Any) -> None:
        """wg-easy expects the whole client: read it, change fields, write it back."""
        current = await self.client(cid)
        body = {k: current.get(k) for k in UPDATE_FIELDS} | changes
        await self._call("POST", f"/client/{cid}", body)

    async def set_enabled(self, cid: int, enabled: bool) -> None:
        await self._call("POST", f"/client/{cid}/{'enable' if enabled else 'disable'}")

    async def delete(self, cid: int) -> None:
        await self._call("DELETE", f"/client/{cid}")

    async def configuration(self, cid: int) -> str:
        text: str = await self._call("GET", f"/client/{cid}/configuration", raw=True)
        return text

    async def qrcode(self, cid: int) -> str:
        text: str = await self._call("GET", f"/client/{cid}/qrcode.svg", raw=True)
        return text

    async def nat_all_interfaces(self) -> None:
        hooks = {"preUp": "", "postUp": POST_UP, "preDown": "", "postDown": POST_DOWN}
        await self._call("POST", "/admin/hooks", hooks)
