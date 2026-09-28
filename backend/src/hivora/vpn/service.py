"""Drive the WireGuard server declared by the template's `vpn` section.

Peers live in the database; every change rewrites the server config in the
app's volume and applies it live by exec (`wg syncconf`): no API, no web UI.
"""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.core.errors import ConflictError, NotFoundError
from hivora.crypto.cipher import Purpose, Sealed
from hivora.docker_gateway import ContainerInfo
from hivora.jobs import Job
from hivora.runtime import Runtime
from hivora.templates.schema import Vpn
from hivora.vpn import wireguard as wg
from hivora.vpn.models import VpnPeer

# ponytail: one lock for every VPN (peer changes are rare); per-app locks if that ever matters
_LOCK = asyncio.Lock()


class NotAVpnError(NotFoundError):
    code = "not_a_vpn"


class VpnClientNotFoundError(NotFoundError):
    code = "vpn_client_not_found"


class VpnFullError(ConflictError):
    code = "vpn_full"


class VpnApplyError(ConflictError):
    code = "vpn_apply_failed"


@dataclass(frozen=True, slots=True)
class _Vpn:
    app_id: int
    slug: str
    spec: Vpn
    container: ContainerInfo | None
    values: dict[str, Any]
    host_config: Path  # the server config on the host
    config: str  # the same file inside the container

    @property
    def zones(self) -> list[str]:
        return [z for z in str(self.values.get(self.spec.zones_field or "") or "").split(",") if z]

    def value(self, field: str | None, default: str = "") -> str:
        return str(self.values.get(field or "") or default)


def _context(app_id: int, public_key: str) -> str:
    return f"vpn:{app_id}:{public_key}"


class VpnTools:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def _vpn(self, app_id: int) -> _Vpn:
        async with self.rt.sessions() as session:
            app, entry, container = await self.rt.apps.main_container(session, app_id)
            spec = entry.template.vpn if entry else None
            if entry is None or spec is None:
                raise NotAVpnError("this app is not a managed VPN", slug=app.slug)
            values = (await self.rt.apps.current_settings(session, app_id)).values
        main = entry.template.services[entry.template.main_service]
        target = next(v.target for v in main.volumes if v.name == spec.volume)
        host = self.rt.apps.volumes_dir(app.slug) / spec.volume / spec.config
        return _Vpn(app.id, app.slug, spec, container, values, host,
                    f"{target.rstrip('/')}/{spec.config}")  # fmt: skip

    def _seal(self, app_id: int, private: str, public: str) -> Sealed:
        return self.rt.box.seal(Purpose.VPN, private, _context(app_id, public))

    def _private(self, peer: VpnPeer) -> str:
        sealed = Sealed(peer.private_nonce, peer.private_key)
        return self.rt.box.open(Purpose.VPN, sealed, _context(peer.app_id, peer.public_key))

    async def _peers(self, session: AsyncSession, vpn: _Vpn) -> tuple[VpnPeer, list[VpnPeer]]:
        """The server's key pair (created on first use) and the clients."""
        rows = list(await session.scalars(
            select(VpnPeer).where(VpnPeer.app_id == vpn.app_id).order_by(VpnPeer.id)
        ))  # fmt: skip
        server = next((p for p in rows if p.server), None)
        if server is None:
            private, public = wg.keypair()
            sealed = self._seal(vpn.app_id, private, public)
            server = VpnPeer(app_id=vpn.app_id, server=True, name="server", public_key=public,
                             address=wg.server_address(vpn.spec.subnet), enabled=True,
                             private_nonce=sealed.nonce, private_key=sealed.ciphertext)  # fmt: skip
            session.add(server)
            await session.flush()
        return server, [p for p in rows if not p.server]

    async def _sync(self, session: AsyncSession, vpn: _Vpn) -> None:
        """Rewrite the server config from the database, then apply it if the VPN runs."""
        server, clients = await self._peers(session, vpn)
        s = vpn.spec
        text = wg.server_conf(self._private(server), s.subnet, s.port, s.interface, [
            wg.Peer(c.name, c.address, c.public_key) for c in clients if c.enabled
        ])  # fmt: skip
        vpn.host_config.parent.mkdir(parents=True, exist_ok=True)
        tmp = vpn.host_config.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds a private key
        with os.fdopen(fd, "w") as f:
            f.write(text)
        tmp.replace(vpn.host_config)
        if vpn.container is None:
            return  # the image brings it up on start
        i, c = s.interface, vpn.config
        code, out = await self.rt.gateway.exec_run(vpn.container.id, ["sh", "-c", (
            f"if wg show {i} >/dev/null 2>&1; then wg-quick strip {c} > /tmp/{i}.conf"
            f" && wg syncconf {i} /tmp/{i}.conf; else wg-quick up {c}; fi"
        )])  # fmt: skip
        if code != 0:
            raise VpnApplyError("WireGuard refused the configuration", output=out[-500:])

    async def _client(self, session: AsyncSession, vpn: _Vpn, cid: int) -> VpnPeer:
        peer = await session.get(VpnPeer, cid)
        if peer is None or peer.app_id != vpn.app_id or peer.server:
            raise VpnClientNotFoundError("unknown VPN client", id=cid)
        return peer

    async def overview(self, app_id: int) -> dict[str, Any]:
        vpn = await self._vpn(app_id)
        stats: dict[str, wg.PeerStats] = {}
        async with _LOCK, self.rt.sessions() as session, session.begin():
            _, clients = await self._peers(session, vpn)
            if vpn.container is not None:
                cmd = ["wg", "show", vpn.spec.interface, "dump"]
                code, out = await self.rt.gateway.exec_run(vpn.container.id, cmd)
                if code != 0:  # interface down (first start, config lost): bring it back
                    await self._sync(session, vpn)
                    code, out = await self.rt.gateway.exec_run(vpn.container.id, cmd)
                stats = wg.parse_dump(out) if code == 0 else {}
        none = wg.PeerStats(None, 0, 0)
        return {"running": vpn.container is not None, "zones": vpn.zones, "clients": [{
            "id": c.id, "name": c.name, "address": c.address, "enabled": c.enabled,
            "allowed_ips": c.allowed_ips, "public_key": c.public_key,
            "latest_handshake": stats.get(c.public_key, none).latest_handshake,
            "rx": stats.get(c.public_key, none).rx, "tx": stats.get(c.public_key, none).tx,
        } for c in clients]}  # fmt: skip

    async def create(self, app_id: int, name: str, allowed_ips: list[str] | None) -> int:
        vpn = await self._vpn(app_id)
        async with _LOCK, self.rt.sessions() as session, session.begin():
            server, clients = await self._peers(session, vpn)
            used = {server.address, *(c.address for c in clients)}
            address = wg.free_address(vpn.spec.subnet, used)
            if address is None:
                raise VpnFullError("no address left in the VPN network")
            private, public = wg.keypair()
            sealed = self._seal(vpn.app_id, private, public)
            peer = VpnPeer(app_id=vpn.app_id, name=name, address=address, enabled=True,
                           allowed_ips=allowed_ips or None, public_key=public,
                           private_nonce=sealed.nonce, private_key=sealed.ciphertext)  # fmt: skip
            session.add(peer)
            await session.flush()
            await self._sync(session, vpn)
        self.rt.bus.publish("vpn.client_created", app=vpn.slug, target=name)
        return peer.id

    async def update(self, app_id: int, cid: int, *, enabled: bool | None,
                     allowed_ips: list[str] | None, clear_allowed: bool) -> None:  # fmt: skip
        vpn = await self._vpn(app_id)
        async with _LOCK, self.rt.sessions() as session, session.begin():
            peer = await self._client(session, vpn, cid)
            if enabled is not None:
                peer.enabled = enabled
            if allowed_ips is not None or clear_allowed:
                peer.allowed_ips = None if clear_allowed else allowed_ips or None
            await session.flush()
            await self._sync(session, vpn)
        self.rt.bus.publish("vpn.client_updated", app=vpn.slug, target=peer.name)

    async def delete(self, app_id: int, cid: int) -> None:
        vpn = await self._vpn(app_id)
        async with _LOCK, self.rt.sessions() as session, session.begin():
            peer = await self._client(session, vpn, cid)
            await session.delete(peer)
            await session.flush()
            await self._sync(session, vpn)
        self.rt.bus.publish("vpn.client_deleted", app=vpn.slug, target=peer.name)

    async def renew(self, app_id: int, cid: int) -> int:
        """New key pair, same client (name, address, allowed IPs)."""
        vpn = await self._vpn(app_id)
        async with _LOCK, self.rt.sessions() as session, session.begin():
            peer = await self._client(session, vpn, cid)
            private, public = wg.keypair()
            sealed = self._seal(vpn.app_id, private, public)
            peer.public_key = public
            peer.private_nonce, peer.private_key = sealed.nonce, sealed.ciphertext
            await session.flush()
            await self._sync(session, vpn)
        self.rt.bus.publish("vpn.client_renewed", app=vpn.slug, target=peer.name)
        return peer.id

    async def configuration(self, app_id: int, cid: int) -> str:
        vpn = await self._vpn(app_id)
        async with _LOCK, self.rt.sessions() as session, session.begin():
            server, _ = await self._peers(session, vpn)
            peer = await self._client(session, vpn, cid)
            s = vpn.spec
            host = vpn.value(s.endpoint_field)
            endpoint = f"[{host}]:{s.port}" if ":" in host else f"{host}:{s.port}"
            allowed = ", ".join(peer.allowed_ips or []) or vpn.value(
                s.allowed_ips_field, "0.0.0.0/0"
            )
            text = wg.client_conf(self._private(peer), peer.address, vpn.value(s.dns_field),
                                  server.public_key, endpoint, allowed)  # fmt: skip
        self.rt.bus.publish("vpn.config_downloaded", app=vpn.slug, target=peer.name)
        return text

    async def qrcode(self, app_id: int, cid: int) -> str:
        import segno  # lazy: only when a QR code is shown

        text = await self.configuration(app_id, cid)
        return str(segno.make(text, error="l").svg_inline(scale=4, border=2))

    async def set_zones(self, app_id: int, zones: list[str]) -> Job:
        """Zones reached through the VPN: the container joins their networks (new revision).

        NAT already covers every interface (PostUp), so nothing else changes.
        """
        vpn = await self._vpn(app_id)
        if not vpn.spec.zones_field:
            raise NotAVpnError("this VPN cannot reach zones")
        inputs = {**vpn.values, vpn.spec.zones_field: ",".join(zones)}
        job = await self.rt.apps.update(app_id, inputs)
        self.rt.bus.publish("vpn.zones_changed", app=vpn.slug, zones=zones)
        return job
