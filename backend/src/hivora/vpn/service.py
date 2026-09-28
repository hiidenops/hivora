"""Drive the WireGuard server declared by the template's `vpn` section.

Peers live in the database; every change rewrites the server config in the
app's volume and applies it live by exec (`wg syncconf`): no API, no web UI.
"""

import asyncio
import ipaddress
import logging
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.models import Application
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.crypto.cipher import Purpose, Sealed
from hivora.docker_gateway import ContainerInfo
from hivora.jobs import Job
from hivora.runtime import Runtime
from hivora.templates.schema import Vpn
from hivora.vpn import wireguard as wg
from hivora.vpn.models import VpnPeer

logger = logging.getLogger(__name__)

ACL = "hivora-acl.sh"
ROUTINGS = ("default", "all", "access", "custom")

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


class VpnNetworkError(ValidationError):
    code = "vpn_bad_network"


class VpnAddressError(ValidationError):
    code = "vpn_bad_address"


@dataclass(frozen=True, slots=True)
class _Vpn:
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
        volume = self.rt.apps.volumes_dir(app.slug) / spec.volume
        root = target.rstrip("/")
        return _Vpn(app.id, app.slug, spec, container, values, volume / spec.config,
                    f"{root}/{spec.config}", volume / ACL, f"{root}/{ACL}")  # fmt: skip

    def _seal(self, app_id: int, private: str, public: str) -> Sealed:
        return self.rt.box.seal(Purpose.VPN, private, _context(app_id, public))

    def _set_psk(self, peer: VpnPeer) -> None:
        sealed = self.rt.box.seal(
            Purpose.VPN, wg.preshared(), _context(peer.app_id, "psk:" + peer.public_key)
        )
        peer.psk_nonce, peer.psk = sealed.nonce, sealed.ciphertext

    def _psk(self, peer: VpnPeer) -> str | None:
        if peer.psk is None or peer.psk_nonce is None:
            return None
        return self.rt.box.open(Purpose.VPN, Sealed(peer.psk_nonce, peer.psk),
                                _context(peer.app_id, "psk:" + peer.public_key))  # fmt: skip

    def _private(self, peer: VpnPeer) -> str:
        sealed = Sealed(peer.private_nonce, peer.private_key)
        return self.rt.box.open(Purpose.VPN, sealed, _context(peer.app_id, peer.public_key))

    async def _peers(self, session: AsyncSession, vpn: _Vpn) -> tuple[VpnPeer, list[VpnPeer]]:
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

    def _check_address(self, vpn: _Vpn, address: str, taken: set[str]) -> None:
        subnet, _ = vpn.network()
        try:
            ok = ipaddress.ip_address(address) in set(ipaddress.ip_network(subnet).hosts())
        except ValueError:
            ok = False
        if not ok or address in taken:
            raise VpnAddressError("address outside the VPN network or already used",
                                  field="address", address=address[:45])  # fmt: skip

    async def _zone_subnets(self, vpn: _Vpn) -> dict[str, tuple[str, ...]]:
        """Subnets of the networks this VPN reaches, by zone slug or "@<app>"."""
        if not vpn.zones:
            return {}
        names = {(f"{z[1:]}_default" if z.startswith("@") else f"hivora-zone-{z}"): z
                 for z in vpn.zones}  # fmt: skip
        return {names[n.name]: n.subnets for n in await self.rt.gateway.list_networks()
                if n.name in names}  # fmt: skip

    def _access(self, peer: VpnPeer, vpn: _Vpn, subnets: dict[str, tuple[str, ...]]) -> wg.Access:
        a = peer.access or {"internet": True, "lan": True, "zones": vpn.zones}
        zones = [z for z in a.get("zones") or [] if z in vpn.zones]
        return wg.Access(peer.address, bool(a.get("internet")), bool(a.get("lan")),
                         tuple(n for z in zones for n in subnets.get(z, ())))  # fmt: skip

    def _active(self, peer: VpnPeer) -> bool:
        return peer.enabled and (peer.expires_at is None or peer.expires_at > self.rt.clock.now())

    async def _sync(self, vpn: _Vpn, *, if_changed: bool = False) -> None:
        """Rewrite the server config and access rights, then apply them if the VPN runs.

        Caller holds ``_LOCK``, outside any transaction: the exec into the container
        (``wg-quick up`` can take seconds) never runs with the database locked.
        ``if_changed``: only when a file differs (settings changed, file edited or lost).
        """
        async with self.rt.sessions() as session, session.begin():
            address = await self._write(session, vpn, if_changed=if_changed)
        if address is not None:
            await self._up(vpn, address)

    async def _write(self, session: AsyncSession, vpn: _Vpn, *, if_changed: bool) -> str | None:
        """Write wg0.conf and the access script; the server address to apply, if running."""
        server, clients = await self._peers(session, vpn)
        s = vpn.spec
        subnet, _ = vpn.network()
        active = [c for c in clients if self._active(c)]
        text = wg.server_conf(self._private(server), subnet, server.address, s.port, s.interface,
                              [wg.Peer(c.name, c.address, c.public_key, self._psk(c))
                               for c in active],
                              vpn.acl)  # fmt: skip
        subnets = await self._zone_subnets(vpn)
        acl = wg.acl_script(s.interface, [self._access(c, vpn, subnets) for c in active],
                            sorted({n for nets in subnets.values() for n in nets}))  # fmt: skip
        with suppress(OSError):
            if if_changed and vpn.host_config.read_text() == text \
                    and vpn.host_acl.read_text() == acl:  # fmt: skip
                return None
        vpn.host_config.parent.mkdir(parents=True, exist_ok=True)
        for path, content in ((vpn.host_acl, acl), (vpn.host_config, text)):
            tmp = path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # private key inside
            with os.fdopen(fd, "w") as f:
                f.write(content)
            tmp.replace(path)
        # Not running: the image brings it up on start (PostUp runs the access rights).
        return server.address if vpn.container is not None else None

    async def _up(self, vpn: _Vpn, address: str) -> None:
        assert vpn.container is not None
        s = vpn.spec
        subnet, _ = vpn.network()
        # Same address: peers and rights applied live. New addressing: interface rebuilt.
        # ponytail: the old network's NAT rule stays until the container restarts (harmless)
        i, c = s.interface, vpn.config
        inet = f"inet {address}/{ipaddress.ip_network(subnet).prefixlen} "
        code, out = await self.rt.gateway.exec_run(vpn.container.id, ["sh", "-c", (
            f"if wg show {i} >/dev/null 2>&1; then"
            f" if ip -4 -o addr show {i} | grep -qF '{inet}'; then"
            f" wg-quick strip {c} > /tmp/{i}.conf && wg syncconf {i} /tmp/{i}.conf"
            f" && sh {vpn.acl};"
            f" else ip link del {i} && wg-quick up {c}; fi;"
            f" else wg-quick up {c}; fi"
        )])  # fmt: skip
        if code != 0:
            raise VpnApplyError("WireGuard refused the configuration", output=out[-500:])

    async def sync(self, app_id: int) -> None:
        vpn = await self._vpn(app_id)
        async with _LOCK:
            await self._sync(vpn)

    async def _client(self, session: AsyncSession, vpn: _Vpn, cid: int) -> VpnPeer:
        peer = await session.get(VpnPeer, cid)
        if peer is None or peer.app_id != vpn.app_id or peer.server:
            raise VpnClientNotFoundError("unknown VPN client", id=cid)
        return peer

    async def overview(self, app_id: int) -> dict[str, Any]:
        vpn = await self._vpn(app_id)
        stats: dict[str, wg.PeerStats] = {}
        async with _LOCK:
            with suppress(VpnApplyError):  # listing still works; the next change reports it
                await self._sync(vpn, if_changed=True)
            async with self.rt.sessions() as session, session.begin():
                _, clients = await self._peers(session, vpn)
            if vpn.container is not None:
                cmd = ["wg", "show", vpn.spec.interface, "dump"]
                code, out = await self.rt.gateway.exec_run(vpn.container.id, cmd)
                if code != 0:  # interface down (first start, config lost): bring it back
                    await self._sync(vpn)
                    code, out = await self.rt.gateway.exec_run(vpn.container.id, cmd)
                now = self.rt.clock.now().timestamp()
                stats = wg.parse_dump(out, now) if code == 0 else {}
        none = wg.PeerStats(None, 0, 0)
        subnet, server_ip = vpn.network()
        return {"running": vpn.container is not None, "zones": vpn.zones, "subnet": subnet,
                "server_address": server_ip,
                "default_allowed_ips": vpn.value(vpn.spec.allowed_ips_field, "0.0.0.0/0"),
                "clients": [self._client_out(c, vpn, stats.get(c.public_key, none))
                            for c in clients]}  # fmt: skip

    def _client_out(self, c: VpnPeer, vpn: _Vpn, st: wg.PeerStats) -> dict[str, Any]:
        a = self._access(c, vpn, {})
        zones = [z for z in (c.access or {"zones": vpn.zones}).get("zones") or [] if z in vpn.zones]
        return {
            "id": c.id, "name": c.name, "address": c.address, "enabled": c.enabled,
            "active": self._active(c), "expires_at": c.expires_at,
            "access": {"internet": a.internet, "lan": a.lan, "zones": zones},
            "routing": c.routing, "allowed_ips": c.allowed_ips, "public_key": c.public_key,
            "latest_handshake": st.latest_handshake, "online": st.online,
            "endpoint": st.endpoint, "rx": st.rx, "tx": st.tx,
        }  # fmt: skip

    async def create(self, app_id: int, name: str, allowed_ips: list[str] | None,
                     address: str | None = None, **changes: Any) -> int:  # fmt: skip
        vpn = await self._vpn(app_id)
        async with _LOCK:
            async with self.rt.sessions() as session, session.begin():
                server, clients = await self._peers(session, vpn)
                used = {server.address, *(c.address for c in clients)}
                if address:
                    self._check_address(vpn, address, used)
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
                self._apply(peer, changes)
                session.add(peer)
                await session.flush()
            try:
                await self._sync(vpn)
            except VpnApplyError:  # refused by WireGuard: the client is not kept
                async with self.rt.sessions() as session, session.begin():
                    await session.delete(await session.get(VpnPeer, peer.id))
                    await session.flush()
                    await self._write(session, vpn, if_changed=False)
                raise
        self.rt.bus.publish("vpn.client_created", app=vpn.slug, target=name)
        return peer.id

    def _apply(self, peer: VpnPeer, changes: dict[str, Any]) -> None:
        """Fields sent by the API (only those present change)."""
        if "name" in changes:
            peer.name = changes["name"]
        if "access" in changes:
            peer.access = changes["access"]
        if "expires_at" in changes:
            at = changes["expires_at"]
            peer.expires_at = at.replace(tzinfo=UTC) if at and at.tzinfo is None else at
        if "routing" in changes:
            peer.routing = changes["routing"]
        if changes.get("allowed_ips"):
            peer.allowed_ips, peer.routing = changes["allowed_ips"], "custom"
        if changes.get("clear_allowed_ips"):
            peer.allowed_ips, peer.routing = None, "default"
        if changes.get("enabled") is not None:
            peer.enabled = changes["enabled"]
            if peer.enabled and not self._active(peer):
                peer.expires_at = None  # re-enabled by hand after expiring

    async def update(self, app_id: int, cid: int, **changes: Any) -> None:
        vpn = await self._vpn(app_id)
        async with _LOCK:
            async with self.rt.sessions() as session, session.begin():
                server, clients = await self._peers(session, vpn)
                peer = await self._client(session, vpn, cid)
                address = changes.pop("address", None)
                if address and address != peer.address:
                    taken = {server.address, *(c.address for c in clients if c is not peer)}
                    self._check_address(vpn, address, taken)
                    peer.address = address
                self._apply(peer, changes)
                await session.flush()
            await self._sync(vpn)
        self.rt.bus.publish("vpn.client_updated", app=vpn.slug, target=peer.name)

    async def delete(self, app_id: int, cid: int) -> None:
        vpn = await self._vpn(app_id)
        async with _LOCK:
            async with self.rt.sessions() as session, session.begin():
                peer = await self._client(session, vpn, cid)
                await session.delete(peer)
                await session.flush()
            await self._sync(vpn)
        self.rt.bus.publish("vpn.client_deleted", app=vpn.slug, target=peer.name)

    async def renew(self, app_id: int, cid: int) -> int:
        """New key pair, same client (name, address, allowed IPs)."""
        vpn = await self._vpn(app_id)
        async with _LOCK:
            async with self.rt.sessions() as session, session.begin():
                peer = await self._client(session, vpn, cid)
                private, public = wg.keypair()
                sealed = self._seal(vpn.app_id, private, public)
                peer.public_key = public
                peer.private_nonce, peer.private_key = sealed.nonce, sealed.ciphertext
                self._set_psk(peer)
                await session.flush()
            await self._sync(vpn)
        self.rt.bus.publish("vpn.client_renewed", app=vpn.slug, target=peer.name)
        return peer.id

    async def configuration(self, app_id: int, cid: int) -> str:
        vpn = await self._vpn(app_id)
        async with _LOCK, self.rt.sessions() as session, session.begin():
            server, _ = await self._peers(session, vpn)
            peer = await self._client(session, vpn, cid)
            s = vpn.spec
            host = vpn.value(s.endpoint_field)
            port = vpn.endpoint_port
            endpoint = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            default = vpn.value(s.allowed_ips_field, "0.0.0.0/0")
            if peer.routing == "all":
                allowed = "0.0.0.0/0"
            elif peer.routing == "access":
                access = self._access(peer, vpn, await self._zone_subnets(vpn))
                allowed = ", ".join(wg.routes(vpn.network()[0], access))
            elif peer.routing == "custom":
                allowed = ", ".join(peer.allowed_ips or []) or default
            else:
                allowed = default
            text = wg.client_conf(
                self._private(peer), peer.address, vpn.value(s.dns_field),
                server.public_key, endpoint, allowed, self._psk(peer),
            )  # fmt: skip
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


async def follow_deploys(rt: Runtime) -> None:
    """After each deploy or settings change of a VPN, rewrite and apply its config."""
    async with rt.bus.subscribe("app.deployed") as sub:
        async for event in sub:
            # ponytail: fixed wait for the state to see the new container (< 2 s budget)
            await asyncio.sleep(3)
            try:
                async with rt.sessions() as session:
                    app_id = await session.scalar(
                        select(Application.id).where(Application.slug == event.payload["app"])
                    )
                if app_id is not None:
                    await VpnTools(rt).sync(app_id)
            except NotAVpnError:
                pass
            except Exception:
                logger.exception("VPN config not applied after deploy", extra=event.payload)


async def expire_clients(rt: Runtime, every: float = 60) -> None:
    """Disable clients whose access expired (the config drops them)."""
    while True:
        await asyncio.sleep(every)
        try:
            async with rt.sessions() as session, session.begin():
                rows = list(await session.scalars(select(VpnPeer).where(
                    VpnPeer.enabled.is_(True), VpnPeer.expires_at <= rt.clock.now()
                )))  # fmt: skip
                for p in rows:
                    p.enabled = False
            for app_id in {p.app_id for p in rows}:
                await VpnTools(rt).sync(app_id)
            for p in rows:
                rt.bus.publish("vpn.client_expired", app_id=p.app_id, target=p.name)
        except Exception:
            logger.exception("VPN expiry check failed")
