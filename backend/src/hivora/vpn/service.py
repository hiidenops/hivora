"""Drive the WireGuard server declared by the template's `vpn` section.

Peers live in the database; every change rewrites the server config in the
app's volume and applies it live by exec (`wg syncconf`): no API, no web UI.
"""

import asyncio
import ipaddress
import logging
from contextlib import suppress
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.queries import app_id_by_slug
from hivora.apps.service import AppService
from hivora.core.clock import Clock
from hivora.core.errors import NotFoundError
from hivora.core.events import EventBus
from hivora.crypto.cipher import Purpose, Sealed, SecretBox
from hivora.docker_gateway import DockerGateway
from hivora.jobs import Job
from hivora.vpn import wireguard as wg
from hivora.vpn.acl import access_of, apply_changes, client_out, is_active
from hivora.vpn.addressing import VpnApp, VpnFullError, allowed_ips, check_address
from hivora.vpn.apply import VpnApplyError, bring_up, write_files, zone_subnets
from hivora.vpn.models import VpnPeer

logger = logging.getLogger(__name__)

ACL = "hivora-acl.sh"

# ponytail: one lock for every VPN (peer changes are rare); per-app locks if that ever matters


class NotAVpnError(NotFoundError):
    code = "not_a_vpn"


class VpnClientNotFoundError(NotFoundError):
    code = "vpn_client_not_found"


def _context(app_id: int, public_key: str) -> str:
    return f"vpn:{app_id}:{public_key}"


class VpnTools:
    """One instance per Hivora (built by Runtime): its lock serializes every change to the
    VPNs' clients and configurations, from the routes and the background tasks alike."""

    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], apps: AppService, box: SecretBox,
        bus: EventBus, clock: Clock, gateway: DockerGateway,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.apps = apps
        self.box = box
        self.bus = bus
        self.clock = clock
        self.gateway = gateway
        self._lock = asyncio.Lock()

    async def _vpn(self, app_id: int) -> VpnApp:
        async with self.sessions() as session:
            app, entry, container = await self.apps.main_container(session, app_id)
            spec = entry.template.vpn if entry else None
            if entry is None or spec is None:
                raise NotAVpnError("this app is not a managed VPN", slug=app.slug)
            values = (await self.apps.planner.current_settings(session, app_id)).values
        main = entry.template.services[entry.template.main_service]
        target = next(v.target for v in main.volumes if v.name == spec.volume)
        volume = self.apps.volumes_dir(app.slug) / spec.volume
        root = target.rstrip("/")
        return VpnApp(app.id, app.slug, spec, container, values, volume / spec.config,
                    f"{root}/{spec.config}", volume / ACL, f"{root}/{ACL}")  # fmt: skip

    def _seal(self, app_id: int, private: str, public: str) -> Sealed:
        return self.box.seal(Purpose.VPN, private, _context(app_id, public))

    def _set_psk(self, peer: VpnPeer) -> None:
        sealed = self.box.seal(
            Purpose.VPN, wg.preshared(), _context(peer.app_id, "psk:" + peer.public_key)
        )
        peer.psk_nonce, peer.psk = sealed.nonce, sealed.ciphertext

    def _psk(self, peer: VpnPeer) -> str | None:
        if peer.psk is None or peer.psk_nonce is None:
            return None
        return self.box.open(Purpose.VPN, Sealed(peer.psk_nonce, peer.psk),
                                _context(peer.app_id, "psk:" + peer.public_key))  # fmt: skip

    def _private(self, peer: VpnPeer) -> str:
        sealed = Sealed(peer.private_nonce, peer.private_key)
        return self.box.open(Purpose.VPN, sealed, _context(peer.app_id, peer.public_key))

    async def _peers(self, session: AsyncSession, vpn: VpnApp) -> tuple[VpnPeer, list[VpnPeer]]:
        """The server's key pair (created on first use) and the clients.

        Follows the addressing settings: the server takes its configured address,
        clients outside the network (or on the server's address) are renumbered.
        """
        subnet, server_ip = vpn.network()
        rows = list(await session.scalars(
            select(VpnPeer).where(VpnPeer.app_id == vpn.app_id).order_by(VpnPeer.id)
        ))  # fmt: skip
        server = next((p for p in rows if p.server), None)
        clients = [p for p in rows if not p.server]
        if server is None:
            private, public = wg.keypair()
            sealed = self._seal(vpn.app_id, private, public)
            server = VpnPeer(app_id=vpn.app_id, server=True, name="server", public_key=public,
                             address=server_ip, enabled=True,
                             private_nonce=sealed.nonce, private_key=sealed.ciphertext)  # fmt: skip
            session.add(server)
        hosts = {str(h) for h in ipaddress.ip_network(subnet).hosts()}
        used = {server_ip}
        moved = [server] if server.address != server_ip else []
        for c in clients:
            if c.address in hosts and c.address not in used:
                used.add(c.address)
            else:
                moved.append(c)
        for c in clients:
            if c.psk is None:  # clients made before preshared keys: one now (config to re-import)
                self._set_psk(c)
        if moved:  # placeholders first: the (app, address) pair stays unique at each step
            for p in moved:
                p.address = f"-{id(p)}"
            await session.flush()
            for p in moved:
                address = server_ip if p is server else wg.free_address(subnet, used)
                if address is None:
                    raise VpnFullError("no address left in the VPN network")
                p.address = address
                used.add(address)
        await session.flush()
        return server, clients

    def _active(self, peer: VpnPeer) -> bool:
        return is_active(peer, self.clock.now())

    async def _sync(self, vpn: VpnApp, *, if_changed: bool = False) -> None:
        """Rewrite the server config and access rights, then apply them if the VPN runs.

        Caller holds ``self._lock``, outside any transaction: the exec into the container
        (``wg-quick up`` can take seconds) never runs with the database locked.
        ``if_changed``: only when a file differs (settings changed, file edited or lost).
        """
        async with self.sessions() as session, session.begin():
            address = await self._write(session, vpn, if_changed=if_changed)
        if address is not None:
            await bring_up(self.gateway, vpn, address)

    async def _write(self, session: AsyncSession, vpn: VpnApp, *, if_changed: bool) -> str | None:
        """Write wg0.conf and the access script; the server address to apply, if running."""
        server, clients = await self._peers(session, vpn)
        s = vpn.spec
        subnet, _ = vpn.network()
        active = [c for c in clients if self._active(c)]
        text = wg.server_conf(self._private(server), subnet, server.address, s.port, s.interface,
                              [wg.Peer(c.name, c.address, c.public_key, self._psk(c))
                               for c in active],
                              vpn.acl)  # fmt: skip
        subnets = await zone_subnets(self.gateway, vpn)
        acl = wg.acl_script(s.interface, [access_of(c, vpn, subnets) for c in active],
                            sorted({n for nets in subnets.values() for n in nets}))  # fmt: skip
        if not write_files(vpn, text, acl, if_changed=if_changed):
            return None
        # Not running: the image brings it up on start (PostUp runs the access rights).
        return server.address if vpn.container is not None else None

    async def sync(self, app_id: int) -> None:
        vpn = await self._vpn(app_id)
        async with self._lock:
            await self._sync(vpn)

    async def _client(self, session: AsyncSession, vpn: VpnApp, cid: int) -> VpnPeer:
        peer = await session.get(VpnPeer, cid)
        if peer is None or peer.app_id != vpn.app_id or peer.server:
            raise VpnClientNotFoundError("unknown VPN client", id=cid)
        return peer

    async def overview(self, app_id: int) -> dict[str, Any]:
        vpn = await self._vpn(app_id)
        stats: dict[str, wg.PeerStats] = {}
        async with self._lock:
            with suppress(VpnApplyError):  # listing still works; the next change reports it
                await self._sync(vpn, if_changed=True)
            async with self.sessions() as session, session.begin():
                _, clients = await self._peers(session, vpn)
            if vpn.container is not None:
                cmd = ["wg", "show", vpn.spec.interface, "dump"]
                code, out = await self.gateway.exec_run(vpn.container.id, cmd)
                if code != 0:  # interface down (first start, config lost): bring it back
                    await self._sync(vpn)
                    code, out = await self.gateway.exec_run(vpn.container.id, cmd)
                now = self.clock.now().timestamp()
                stats = wg.parse_dump(out, now) if code == 0 else {}
        none = wg.PeerStats(None, 0, 0)
        subnet, server_ip = vpn.network()
        return {"running": vpn.container is not None, "zones": vpn.zones, "subnet": subnet,
                "server_address": server_ip,
                "default_allowed_ips": vpn.default_allowed_ips,
                "clients": [client_out(c, vpn, stats.get(c.public_key, none), self.clock.now())
                            for c in clients]}  # fmt: skip

    async def create(self, app_id: int, name: str, allowed_ips: list[str] | None,
                     address: str | None = None, **changes: Any) -> int:  # fmt: skip
        vpn = await self._vpn(app_id)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                server, clients = await self._peers(session, vpn)
                used = {server.address, *(c.address for c in clients)}
                if address:
                    check_address(vpn, address, used)
                address = address or wg.free_address(vpn.network()[0], used)
                if address is None:
                    raise VpnFullError("no address left in the VPN network")
                private, public = wg.keypair()
                sealed = self._seal(vpn.app_id, private, public)
                peer = VpnPeer(app_id=vpn.app_id, name=name, address=address, enabled=True,
                               allowed_ips=allowed_ips or None, public_key=public,
                               routing="custom" if allowed_ips else "default",
                               private_nonce=sealed.nonce,
                               private_key=sealed.ciphertext)  # fmt: skip
                self._set_psk(peer)
                apply_changes(peer, changes, self.clock.now())
                session.add(peer)
                await session.flush()
            try:
                await self._sync(vpn)
            except VpnApplyError:  # refused by WireGuard: the client is not kept
                async with self.sessions() as session, session.begin():
                    await session.delete(await session.get(VpnPeer, peer.id))
                    await session.flush()
                    await self._write(session, vpn, if_changed=False)
                raise
        self.bus.publish("vpn.client_created", app=vpn.slug, target=name)
        return peer.id

    async def update(self, app_id: int, cid: int, **changes: Any) -> None:
        vpn = await self._vpn(app_id)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                server, clients = await self._peers(session, vpn)
                peer = await self._client(session, vpn, cid)
                address = changes.pop("address", None)
                if address and address != peer.address:
                    taken = {server.address, *(c.address for c in clients if c is not peer)}
                    check_address(vpn, address, taken)
                    peer.address = address
                apply_changes(peer, changes, self.clock.now())
                await session.flush()
            await self._sync(vpn)
        self.bus.publish("vpn.client_updated", app=vpn.slug, target=peer.name)

    async def delete(self, app_id: int, cid: int) -> None:
        vpn = await self._vpn(app_id)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                peer = await self._client(session, vpn, cid)
                await session.delete(peer)
                await session.flush()
            await self._sync(vpn)
        self.bus.publish("vpn.client_deleted", app=vpn.slug, target=peer.name)

    async def renew(self, app_id: int, cid: int) -> int:
        """New key pair, same client (name, address, allowed IPs)."""
        vpn = await self._vpn(app_id)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                peer = await self._client(session, vpn, cid)
                private, public = wg.keypair()
                sealed = self._seal(vpn.app_id, private, public)
                peer.public_key = public
                peer.private_nonce, peer.private_key = sealed.nonce, sealed.ciphertext
                self._set_psk(peer)
                await session.flush()
            await self._sync(vpn)
        self.bus.publish("vpn.client_renewed", app=vpn.slug, target=peer.name)
        return peer.id

    async def configuration(self, app_id: int, cid: int, *, quiet: bool = False) -> str:
        """``quiet``: written by Hivora itself (admin.conf), not downloaded: not audited."""
        vpn = await self._vpn(app_id)
        async with self._lock, self.sessions() as session, session.begin():
            server, _ = await self._peers(session, vpn)
            peer = await self._client(session, vpn, cid)
            access = (access_of(peer, vpn, await zone_subnets(self.gateway, vpn))
                      if peer.routing == "access" else None)  # fmt: skip
            allowed = allowed_ips(vpn, peer.routing, peer.allowed_ips, access)
            text = wg.client_conf(
                self._private(peer), peer.address, vpn.value(vpn.spec.dns_field),
                server.public_key, vpn.endpoint, allowed, self._psk(peer),
            )  # fmt: skip
        if not quiet:
            self.bus.publish("vpn.config_downloaded", app=vpn.slug, target=peer.name)
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
        job = await self.apps.revisions.update(app_id, inputs)
        self.bus.publish("vpn.zones_changed", app=vpn.slug, zones=zones)
        return job


async def follow_deploys(vpn: VpnTools) -> None:
    """After each deploy or settings change of a VPN, rewrite and apply its config."""
    async with vpn.bus.subscribe("app.deployed") as sub:
        async for event in sub:
            # ponytail: fixed wait for the state to see the new container (< 2 s budget)
            await asyncio.sleep(3)
            try:
                async with vpn.sessions() as session:
                    app_id = await app_id_by_slug(session, event.payload["app"])
                if app_id is not None:
                    await vpn.sync(app_id)
            except NotAVpnError:
                pass
            except Exception:
                logger.exception("VPN config not applied after deploy", extra=event.payload)


async def expire_clients(vpn: VpnTools, every: float = 60) -> None:
    """Disable clients whose access expired (the config drops them)."""
    while True:
        await asyncio.sleep(every)
        try:
            async with vpn.sessions() as session, session.begin():
                rows = list(await session.scalars(select(VpnPeer).where(
                    VpnPeer.enabled.is_(True), VpnPeer.expires_at <= vpn.clock.now()
                )))  # fmt: skip
                for p in rows:
                    p.enabled = False
            for app_id in {p.app_id for p in rows}:
                await vpn.sync(app_id)
            for p in rows:
                vpn.bus.publish("vpn.client_expired", app_id=p.app_id, target=p.name)
        except Exception:
            logger.exception("VPN expiry check failed")
