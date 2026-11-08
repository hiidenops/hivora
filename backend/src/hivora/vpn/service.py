"""Drive the WireGuard server declared by the template's `vpn` section.

Peers live in the database; every change rewrites the server config in the
app's volume and applies it live by exec (`wg syncconf`): no API, no web UI.
"""

import asyncio
import ipaddress
import logging
import os
from contextlib import suppress
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.addressing import Taken
from hivora.apps.core import latest_revision
from hivora.apps.models import Application
from hivora.apps.planner import vpn_zone_slugs
from hivora.apps.queries import app_id_by_slug
from hivora.apps.service import AppService
from hivora.core.clock import Clock
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.crypto.cipher import Purpose, Sealed, SecretBox
from hivora.docker_gateway import DockerGateway
from hivora.jobs import Job, JobContext, JobKind, JobStatus
from hivora.sites.core import SERVICE as SITE_SERVICE
from hivora.sites.views import sites_by_host
from hivora.vpn import dns, web
from hivora.vpn import wireguard as wg
from hivora.vpn.acl import access_of, apply_changes, client_out, is_active
from hivora.vpn.addressing import VpnApp, VpnFullError, allowed_ips, check_address
from hivora.vpn.apply import VpnApplyError, bring_up, write_files, zone_subnets
from hivora.vpn.models import VpnDnsRecord, VpnPeer
from hivora.zones.models import NetworkMode, Zone
from hivora.zones.service import list_zones, zone_network

logger = logging.getLogger(__name__)

ACL = "hivora-acl.sh"
COREFILE = "coredns/Corefile"  # in the config volume: the image's CoreDNS reads it
RESTART_DNS = ["s6-svc", "-r", "/run/service/svc-coredns"]

# ponytail: one lock for every VPN (peer changes are rare); per-app locks if that ever matters


class NotAVpnError(NotFoundError):
    code = "not_a_vpn"


class ZoneTakenError(ConflictError):
    code = "vpn_zone_taken"


class VpnClientNotFoundError(NotFoundError):
    code = "vpn_client_not_found"


class DnsRecordNotFoundError(NotFoundError):
    code = "vpn_dns_record_not_found"


class DnsNameTakenError(ConflictError):
    code = "vpn_dns_name_taken"


class DnsTargetError(ConflictError):
    code = "vpn_dns_bad_target"


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
        self._web_applied = "[]"  # the routes the web proxy serves (none until a job says)

    async def _vpn(self, app_id: int) -> VpnApp:
        async with self.sessions() as session:
            app, entry, container = await self.apps.main_container(session, app_id)
            spec = entry.template.vpn if entry else None
            if entry is None or spec is None:
                raise NotAVpnError("this app is not a managed VPN", slug=app.slug)
            values = (await self.apps.planner.current_settings(session, app_id)).values
            rev = await latest_revision(session, app_id)
        main = entry.template.services[entry.template.main_service]
        target = next(v.target for v in main.volumes if v.name == spec.volume)
        volume = self.apps.volumes_dir(app.slug) / spec.volume
        root = target.rstrip("/")
        return VpnApp(app.id, app.slug, spec, container, values, volume / spec.config,
                      f"{root}/{spec.config}", volume / ACL, f"{root}/{ACL}",
                      volume / COREFILE, _runs_dns(rev.compose_yaml if rev else "",
                                                   entry.template.main_service))  # fmt: skip

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
            dns_changed = await self._write_dns(session, vpn)
        if address is not None:
            await bring_up(self.gateway, vpn, address)
        if dns_changed and vpn.local_dns and vpn.container is not None:
            code, out = await self.gateway.exec_run(vpn.container.id, RESTART_DNS)
            if code != 0:
                logger.warning(
                    "VPN local DNS not restarted", extra={"app": vpn.slug, "output": out[-300:]}
                )

    async def _records(self, session: AsyncSession, vpn: VpnApp) -> list[dict[str, Any]]:
        rows = await session.execute(
            select(VpnDnsRecord, Application.slug, Application.name)
            .outerjoin(Application, Application.id == VpnDnsRecord.target_app_id)
            .where(VpnDnsRecord.vpn_app_id == vpn.app_id).order_by(VpnDnsRecord.name)
        )  # fmt: skip
        return [{"id": r.id, "name": r.name, "ip": r.ip, "app_id": r.target_app_id,
                 "app_slug": slug, "app_name": name, "service": r.target_service,
                 "port": r.target_port, "via_proxy": web.via_proxy(r.target_port),
                 "url": f"http://{r.name}" if r.target_port is not None else None}
                for r, slug, name in rows]  # fmt: skip

    async def _targets(self, session: AsyncSession, vpn: VpnApp) -> dict[int, dict[str, Any]]:
        """Apps of the zones the VPN reaches, by id: their main container's Docker name, the
        ports a name can aim at (each service's, web or not) and the sites they host."""
        out = {}
        rows = await session.execute(
            select(Application, Zone.slug).join(Zone, Zone.id == Application.zone_id)
            .where(Zone.slug.in_(vpn.zones), Application.id != vpn.app_id)
            .order_by(Application.name)
        )  # fmt: skip
        hosted = await sites_by_host(session, None)
        for app, zone in rows:
            try:
                entry = await self.apps.planner.entry_of(session, app)
            except (ConflictError, NotFoundError):
                continue  # no template: its main service is unknown
            values = (await self.apps.planner.current_settings(session, app.id)).values
            form = entry.template.with_defaults(values)
            ports = []
            srv = None
            prefix = entry.template.game.srv if entry.template.game else None
            for name, svc in entry.template.services.items():
                for p in svc.ports:
                    with suppress(KeyError, TypeError, ValueError):
                        port = p.container_in(form)
                        ports.append({"service": name, "port": port, "protocol": p.protocol,
                                      "web": p.purpose == "web"})  # fmt: skip
                        if prefix and p.purpose == "game" and srv is None:
                            srv = (prefix, port)
            sites = [{"id": h.id, "name": h.name, "service": SITE_SERVICE,
                      "port": web.DIRECT_PORT if h.main else h.port, "main": h.main}
                     for h in hosted.get(app.id, []) if h.main or h.port]  # fmt: skip
            out[app.id] = {"id": app.id, "name": app.name, "zone": zone, "slug": app.slug,
                           "container": f"{app.slug}-{entry.template.main_service}-1",
                           "ports": ports, "sites": sites, "srv": srv}  # fmt: skip
        return out

    async def _routes(self, session: AsyncSession) -> list[web.Route]:
        """Every name (all VPNs) the web proxy serves: aimed at a port other than 80 of an
        app in a zone with its network."""
        out = []
        rows = await session.execute(
            select(VpnDnsRecord, Application, Zone)
            .join(Application, Application.id == VpnDnsRecord.target_app_id)
            .join(Zone, Zone.id == Application.zone_id)
            .where(VpnDnsRecord.target_port.is_not(None)).order_by(VpnDnsRecord.name)
        )  # fmt: skip
        for record, app, zone in rows:
            network = zone_network(zone)
            if network and web.via_proxy(record.target_port) and record.target_service:
                out.append(web.Route(record.name, web.container_of(app.slug, record.target_service),
                                     int(record.target_port or 0), network))  # fmt: skip
        return out

    async def _web_addresses(self, session: AsyncSession,
                             routes: list[web.Route]) -> dict[str, str]:  # fmt: skip
        """The proxy's fixed address in each network it serves (addressing plan)."""
        if self.apps.addressing is None:
            return {}
        networks = sorted({r.network for r in routes})
        return await self.apps.addressing.for_sidecar(session, web.SLUG, web.SERVICE, networks)

    async def _web_signature(self) -> str:
        async with self.sessions() as session:
            return repr(await self._routes(session))

    def register(self) -> None:
        self.apps.jobs.register(JobKind.VPN_WEB, self._apply_web)

    async def _apply_web(self, ctx: JobContext) -> None:
        """The vpn_web job: the web proxy as the names now need it."""
        async with self.sessions() as session, session.begin():
            routes = await self._routes(session)
            addresses = await self._web_addresses(session, routes)
        signature = repr(routes)
        directory = self.apps.settings.data_dir / "web"
        await ctx.log(await web.apply(self.gateway, directory, routes, addresses))
        self._web_applied = signature

    async def queue_web(self, *, if_changed: bool = True) -> Job | None:
        """The web proxy's job, when the names it serves changed (and none is waiting)."""
        if if_changed and await self._web_signature() == self._web_applied:
            return None
        async with self.sessions() as session, session.begin():
            waiting = await session.scalar(select(Job).where(
                Job.kind == JobKind.VPN_WEB, Job.status == JobStatus.QUEUED))  # fmt: skip
            if waiting is not None:
                return waiting
            job = self.apps.jobs.add(session, JobKind.VPN_WEB)
        self.apps.jobs.wake()
        return job

    async def _write_dns(self, session: AsyncSession, vpn: VpnApp) -> bool:
        """Write the local DNS's Corefile; False when it is as is (or the VPN has none)."""
        if vpn.host_dns is None:
            return False
        targets = await self._targets(session, vpn)
        routes = {r.name: r for r in await self._routes(session)}
        proxy = await self._web_addresses(session, list(routes.values()))
        records = []
        for r in await self._records(session, vpn):
            route = routes.get(r["name"])
            if route and route.network in proxy:  # through the web proxy, in the app's zone
                records.append(dns.Record(r["name"], ip=proxy[route.network]))
                continue
            target = targets.get(r["app_id"] or 0, {})
            container = target.get("container")
            if r["service"] and target:  # one port, given by the app itself (port 80)
                container = web.container_of(target["slug"], r["service"])
            records.append(dns.Record(r["name"], ip=r["ip"], container=container,
                                      srv=None if r["service"] else target.get("srv")))  # fmt: skip
        text = dns.corefile(records, vpn.value(vpn.spec.dns_field))
        with suppress(OSError):
            if vpn.host_dns.read_text() == text:
                return False
        vpn.host_dns.parent.mkdir(parents=True, exist_ok=True)
        tmp = vpn.host_dns.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        tmp.replace(vpn.host_dns)
        return True

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

    async def sync(self, app_id: int, *, if_changed: bool = False) -> None:
        vpn = await self._vpn(app_id)
        async with self._lock:
            await self._sync(vpn, if_changed=if_changed)

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
                self._private(peer), peer.address, vpn.client_dns,
                server.public_key, vpn.endpoint, allowed, self._psk(peer),
            )  # fmt: skip
        if not quiet:
            self.bus.publish("vpn.config_downloaded", app=vpn.slug, target=peer.name)
        return text

    async def qrcode(self, app_id: int, cid: int) -> str:
        import segno  # lazy: only when a QR code is shown

        text = await self.configuration(app_id, cid)
        return str(segno.make(text, error="l").svg_inline(scale=4, border=2))

    async def dns_overview(self, app_id: int) -> dict[str, Any]:
        vpn = await self._vpn(app_id)
        async with self.sessions() as session:
            targets = await self._targets(session, vpn)
            records = await self._records(session, vpn)
        return {"enabled": vpn.local_dns, "server": vpn.network()[1], "records": records,
                "zones": vpn.zones,
                "targets": [{k: t[k] for k in ("id", "name", "zone", "ports", "sites")}
                            for t in targets.values()]}  # fmt: skip

    async def _check_target(self, session: AsyncSession, vpn: VpnApp, ip: str | None,
                            app: int | None, service: str | None,
                            port: int | None) -> str | None:  # fmt: skip
        """An IP, or an app of the zones the VPN reaches, or one of its ports or sites, or
        nothing (a name not linked yet). Returns the IP, canonical."""
        if ip is not None and app is not None:
            raise DnsTargetError("give an IP or an app, not both")
        if ip is not None:
            try:
                return str(ipaddress.ip_address(ip.strip()))
            except ValueError:
                raise DnsTargetError("invalid IP address", field="ip") from None
        if app is None:
            if port is not None:
                raise DnsTargetError("a port needs its app", field="port")
            return None
        target = (await self._targets(session, vpn)).get(app)
        if target is None:
            raise DnsTargetError("this app is not in a zone the VPN reaches", field="app_id")
        if port is not None:
            known = {(p["service"], p["port"]) for p in [*target["ports"], *target["sites"]]}
            if (service, port) not in known:
                raise DnsTargetError("this app has no such port", field="port", port=port)
        return None

    async def dns_create(self, app_id: int, name: str, ip: str | None,
                         target_app_id: int | None, service: str | None = None,
                         port: int | None = None) -> int:  # fmt: skip
        """A name: for an IP, an app of the zones the VPN reaches (one of its ports), or not
        linked yet (a card of the DNS map)."""
        vpn = await self._vpn(app_id)
        name = dns.check_name(name)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                ip = await self._check_target(session, vpn, ip, target_app_id, service, port)
                if await session.scalar(
                    select(VpnDnsRecord.id).where(
                        VpnDnsRecord.vpn_app_id == vpn.app_id, VpnDnsRecord.name == name
                    )
                ):
                    raise DnsNameTakenError("this name already exists", field="name")
                record = VpnDnsRecord(vpn_app_id=vpn.app_id, name=name, ip=ip,
                                      target_app_id=target_app_id,
                                      target_service=service if port is not None else None,
                                      target_port=port)  # fmt: skip
                session.add(record)
                await session.flush()
            await self._sync(vpn)
        await self.queue_web()
        self.bus.publish("vpn.dns_created", app=vpn.slug, target=name)
        return record.id

    async def dns_update(self, app_id: int, rid: int, ip: str | None, target_app_id: int | None,
                         service: str | None, port: int | None) -> None:  # fmt: skip
        """Link a name to another target (an IP, an app, one of its ports), or unlink it."""
        vpn = await self._vpn(app_id)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                record = await session.get(VpnDnsRecord, rid)
                if record is None or record.vpn_app_id != vpn.app_id:
                    raise DnsRecordNotFoundError("unknown DNS name", id=rid)
                record.ip = await self._check_target(session, vpn, ip, target_app_id, service,
                                                     port)  # fmt: skip
                record.target_app_id = target_app_id
                record.target_service = service if port is not None else None
                record.target_port = port
                name = record.name
            await self._sync(vpn)
        await self.queue_web()
        self.bus.publish("vpn.dns_updated", app=vpn.slug, target=name)

    async def dns_delete(self, app_id: int, rid: int) -> None:
        vpn = await self._vpn(app_id)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                record = await session.get(VpnDnsRecord, rid)
                if record is None or record.vpn_app_id != vpn.app_id:
                    raise DnsRecordNotFoundError("unknown DNS name", id=rid)
                name = record.name
                await session.delete(record)
            await self._sync(vpn)
        await self.queue_web()
        self.bus.publish("vpn.dns_deleted", app=vpn.slug, target=name)

    async def subnets(self, session: AsyncSession) -> list[Taken]:
        """The networks of the VPNs (their tunnels): taken for the addressing plan."""
        out = []
        for app in await session.scalars(select(Application)):
            with suppress(ConflictError, NotFoundError):
                entry = await self.apps.planner.entry_of(session, app)
                spec = entry.template.vpn
                if spec is None:
                    continue
                values = (await self.apps.planner.current_settings(session, app.id)).values
                subnet = str(values.get(spec.subnet_field or "") or spec.subnet)
                with suppress(ValueError):
                    out.append(Taken(str(ipaddress.ip_network(subnet, strict=False)),
                                     f"vpn:{app.slug}"))  # fmt: skip
        return out

    async def set_zones(self, app_id: int, zones: list[str]) -> Job:
        """Zones reached through the VPN: the container joins their networks (new revision).

        A zone newly reached gets its apps a network of their own (shared, on a subnet next
        to the VPN's unless chosen by hand; a system zone keeps the installer's) and is
        redeployed:
        nothing of it stays published on the host (the compiler, `vpn_only`).
        NAT already covers every interface (PostUp), so nothing else changes.
        """
        vpn = await self._vpn(app_id)
        if not vpn.spec.zones_field:
            raise NotAVpnError("this VPN cannot reach zones")
        zones = list(dict.fromkeys(vpn_zone_slugs(",".join(zones))))
        added = [z for z in zones if z not in vpn.zones]
        async with self.sessions() as session, session.begin():
            others = await self.apps.planner.vpn_zones(session)
            for slug in added:
                if slug in others and others[slug][0] != vpn.slug:
                    raise ZoneTakenError("this zone is already reached by another VPN",
                                         zone=slug, vpn=others[slug][1])  # fmt: skip
            linked = []
            for zone in (z for z in await list_zones(session) if z.slug in added):
                zone.network_mode = NetworkMode.SHARED
                if self.apps.addressing is not None:  # its subnet: next to the VPN's
                    await self.apps.addressing.follow_vpn(session, zone, vpn.network()[0])
                linked.append(zone.id)
        inputs = {**vpn.values, vpn.spec.zones_field: ",".join(zones)}
        job = await self.apps.revisions.update(app_id, inputs)
        for zone_id in linked:  # their own network, nothing published any more
            await self.apps.revisions.redeploy_zone(zone_id)
        self.bus.publish("vpn.zones_changed", app=vpn.slug, zones=zones)
        return job


async def follow_deploys(vpn: VpnTools) -> None:
    """After each deploy or settings change of a VPN, rewrite and apply its config; of an
    app with names, the DNS of their VPNs (its game port may have changed)."""
    async with vpn.bus.subscribe("app.deployed") as sub:
        async for event in sub:
            # ponytail: fixed wait for the state to see the new container (< 2 s budget)
            await asyncio.sleep(3)
            try:
                async with vpn.sessions() as session:
                    app_id = await app_id_by_slug(session, event.payload["app"])
                    vpns = await session.scalars(select(VpnDnsRecord.vpn_app_id).where(
                        VpnDnsRecord.target_app_id == app_id).distinct())  # fmt: skip
                    named = [] if app_id is None else list(vpns)
                if app_id is not None:
                    with suppress(NotAVpnError):
                        await vpn.sync(app_id)
                for vpn_id in named:
                    await vpn.sync(vpn_id, if_changed=True)
            except Exception:
                logger.exception("VPN config not applied after deploy", extra=event.payload)


async def follow_web(vpn: VpnTools) -> None:
    """The web proxy follows the apps it serves (redeployed in another zone, removed: their
    names change) and comes back after Hivora restarts."""
    with suppress(Exception):  # names to serve, or a proxy left over: applied now
        if await vpn._web_signature() != "[]" or await vpn.gateway.list_containers(web.LABELS):
            await vpn.queue_web(if_changed=False)
    async with vpn.bus.subscribe("app.*") as sub:
        async for event in sub:
            if event.topic not in ("app.deployed", "app.removed"):
                continue
            try:
                await vpn.queue_web()
            except Exception:
                logger.exception("VPN web proxy not followed")


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


def _runs_dns(compose_yaml: str, main: str) -> bool:
    """The deployed revision starts the image's CoreDNS (template 2.4.0 on)."""
    try:
        env = yaml.safe_load(compose_yaml)["services"][main].get("environment") or {}
    except (yaml.YAMLError, KeyError, TypeError, AttributeError):
        return False
    return isinstance(env, dict) and str(env.get("USE_COREDNS", "")).lower() == "true"
