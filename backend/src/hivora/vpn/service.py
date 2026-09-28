"""Drive the VPN app declared by the template's `vpn` section (wg-easy for now)."""

from dataclasses import dataclass
from typing import Any

from hivora.core.errors import ConflictError, NotFoundError
from hivora.jobs import Job
from hivora.runtime import Runtime
from hivora.templates.schema import Vpn
from hivora.vpn.wgeasy import WgEasy


class NotAVpnError(NotFoundError):
    code = "not_a_vpn"


class VpnNotRunningError(ConflictError):
    code = "vpn_not_running"


@dataclass(frozen=True, slots=True)
class _Vpn:
    slug: str
    spec: Vpn
    running: bool
    api: WgEasy | None
    zones: list[str]


def client_out(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(c["id"]), "name": str(c.get("name", "")), "address": c.get("ipv4Address"),
        "enabled": bool(c.get("enabled", True)), "allowed_ips": c.get("allowedIps"),
        "public_key": c.get("publicKey"), "latest_handshake": c.get("latestHandshakeAt"),
        "rx": int(c.get("transferRx") or 0), "tx": int(c.get("transferTx") or 0),
    }  # fmt: skip


class VpnTools:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def _vpn(self, app_id: int) -> _Vpn:
        async with self.rt.sessions() as session:
            app, entry, container = await self.rt.apps.main_container(session, app_id)
            spec = entry.template.vpn if entry else None
            if entry is None or spec is None:
                raise NotAVpnError("this app is not a managed VPN", slug=app.slug)
            secrets = await self.rt.apps.decrypt_secrets(session, app.id)
            values = (await self.rt.apps.current_settings(session, app_id)).values
        zones = [z for z in str(values.get(spec.zones_field or "") or "").split(",") if z]
        api = None
        if container is not None and container.ips:  # app network: the API is never published
            api = WgEasy(f"http://{container.ips[0]}:{spec.api_port}", spec.username,
                         secrets.get(spec.password_secret, ""))  # fmt: skip
        return _Vpn(app.slug, spec, container is not None, api, zones)

    async def _api(self, app_id: int) -> tuple[_Vpn, WgEasy]:
        vpn = await self._vpn(app_id)
        if vpn.api is None:
            raise VpnNotRunningError("start the VPN first")
        return vpn, vpn.api

    async def overview(self, app_id: int) -> dict[str, Any]:
        vpn = await self._vpn(app_id)
        clients = [client_out(c) for c in await vpn.api.clients()] if vpn.api else []
        return {"running": vpn.running, "clients": clients, "zones": vpn.zones}

    async def create(self, app_id: int, name: str, allowed_ips: list[str] | None) -> int:
        vpn, api = await self._api(app_id)
        cid = await api.create(name)
        if allowed_ips:
            await api.update(cid, allowedIps=allowed_ips)
        self.rt.bus.publish("vpn.client_created", app=vpn.slug, target=name)
        return cid

    async def update(self, app_id: int, cid: int, *, enabled: bool | None,
                     allowed_ips: list[str] | None, clear_allowed: bool) -> None:  # fmt: skip
        vpn, api = await self._api(app_id)
        if enabled is not None:
            await api.set_enabled(cid, enabled)
        if allowed_ips is not None or clear_allowed:
            await api.update(cid, allowedIps=None if clear_allowed else allowed_ips)
        self.rt.bus.publish("vpn.client_updated", app=vpn.slug, target=str(cid))

    async def delete(self, app_id: int, cid: int) -> None:
        vpn, api = await self._api(app_id)
        await api.delete(cid)
        self.rt.bus.publish("vpn.client_deleted", app=vpn.slug, target=str(cid))

    async def renew(self, app_id: int, cid: int) -> int:
        """New keys: wg-easy has no rotation, so the client is recreated identically."""
        vpn, api = await self._api(app_id)
        old = await api.client(cid)
        new = await api.create(str(old.get("name") or f"client-{cid}"))
        if old.get("allowedIps"):
            await api.update(new, allowedIps=old["allowedIps"])
        await api.delete(cid)
        self.rt.bus.publish("vpn.client_renewed", app=vpn.slug, target=str(old.get("name")))
        return new

    async def configuration(self, app_id: int, cid: int) -> str:
        vpn, api = await self._api(app_id)
        self.rt.bus.publish("vpn.config_downloaded", app=vpn.slug, target=str(cid))
        return await api.configuration(cid)

    async def qrcode(self, app_id: int, cid: int) -> str:
        _, api = await self._api(app_id)
        return await api.qrcode(cid)

    async def set_zones(self, app_id: int, zones: list[str]) -> Job:
        """Zones reached through the VPN: NAT on every interface, then a new revision."""
        vpn = await self._vpn(app_id)
        if not vpn.spec.zones_field:
            raise NotAVpnError("this VPN cannot reach zones")
        if zones and vpn.api is not None:
            await vpn.api.nat_all_interfaces()
        async with self.rt.sessions() as session:
            values = (await self.rt.apps.current_settings(session, app_id)).values
        job = await self.rt.apps.update(app_id, {**values, vpn.spec.zones_field: ",".join(zones)})
        self.rt.bus.publish("vpn.zones_changed", app=vpn.slug, zones=zones)
        return job
