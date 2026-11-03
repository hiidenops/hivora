"""Drive the HTTPS proxy declared by a template's `proxy` section (one per Hivora).

Domains live in the database; every change rewrites the sites file in the proxy's
volume and reloads Caddy by exec. A domain's app is reached on its zone's network: the
proxy joins it (new revision of the proxy, the zone's apps linked together if needed).
"""

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.models import Application
from hivora.apps.planner import vpn_zone_slugs
from hivora.apps.service import AppService
from hivora.core.clock import Clock
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.docker_gateway import ContainerInfo, DockerGateway
from hivora.jobs import Job
from hivora.proxy import caddy
from hivora.proxy.models import ProxyRoute
from hivora.templates.schema import Proxy, Template
from hivora.zones.models import NetworkMode, Zone

logger = logging.getLogger(__name__)


class ProxyNotInstalledError(ConflictError):
    code = "proxy_not_installed"


class ProxyTargetError(ConflictError):
    code = "proxy_bad_target"


class ProxyDomainTakenError(ConflictError):
    code = "proxy_domain_taken"


class ProxyRouteNotFoundError(NotFoundError):
    code = "proxy_route_not_found"


class ProxyApplyError(ConflictError):
    code = "proxy_apply_failed"


@dataclass(frozen=True, slots=True)
class ProxyApp:
    app_id: int
    slug: str
    spec: Proxy
    container: ContainerInfo | None
    values: dict[str, Any]
    sites: Path  # the sites file on the host
    data: Path  # Caddy's data volume on the host (certificates)

    @property
    def zones(self) -> list[str]:
        return vpn_zone_slugs(self.values.get(self.spec.zones_field))


def web_port(template: Template, values: dict[str, Any]) -> tuple[str, int] | None:
    """(service, container port) of the app's web port, the main service's first."""
    form = template.with_defaults(values)
    main = template.main_service
    for name, svc in sorted(template.services.items(), key=lambda kv: kv[0] != main):
        for p in svc.ports:
            if p.purpose == "web":
                with suppress(KeyError, TypeError, ValueError):
                    return name, p.container_in(form)
    return None


async def resolve(domain: str) -> list[str]:
    """The domain's addresses (A and AAAA) as this machine sees them; [] if none."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(domain, None, type=socket.SOCK_STREAM), 3)
    except (OSError, TimeoutError):
        return []
    return sorted({str(i[4][0]) for i in infos})


class ProxyTools:
    """Its lock serializes every change to the domains and the sites file."""

    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], apps: AppService, bus: EventBus,
        clock: Clock, gateway: DockerGateway, public_ip: Callable[[], str | None],
        resolver: Callable[[str], Awaitable[list[str]]] = resolve,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.apps = apps
        self.bus = bus
        self.clock = clock
        self.gateway = gateway
        self.public_ip = public_ip
        self.resolver = resolver
        self._lock = asyncio.Lock()

    async def _proxy(self, session: AsyncSession) -> ProxyApp | None:
        for app in await session.scalars(select(Application).order_by(Application.id)):
            try:
                entry = await self.apps.planner.entry_of(session, app)
            except (ConflictError, NotFoundError):
                continue
            if (spec := entry.template.proxy) is None:
                continue
            _, _, container = await self.apps.main_container(session, app.id)
            values = (await self.apps.planner.current_settings(session, app.id)).values
            volumes = self.apps.volumes_dir(app.slug)
            sites = volumes / spec.volume / spec.sites
            return ProxyApp(app.id, app.slug, spec, container, values, sites,
                            volumes / spec.data_volume)  # fmt: skip
        return None

    async def _targets(self, session: AsyncSession, proxy: ProxyApp | None) -> dict[int, Any]:
        """Apps a domain can go to, by id: (app, zone, Caddy site minus its domain).
        Not: the proxy, apps without a zone or web port, apps of a zone behind a VPN."""
        behind_vpn = await self.apps.planner.vpn_zones(session)
        out: dict[int, Any] = {}
        rows = await session.execute(
            select(Application, Zone).join(Zone, Zone.id == Application.zone_id)
            .order_by(Application.name)
        )  # fmt: skip
        for app, zone in rows:
            if (proxy and app.id == proxy.app_id) or zone.slug in behind_vpn:
                continue
            try:
                entry = await self.apps.planner.entry_of(session, app)
                values = (await self.apps.planner.current_settings(session, app.id)).values
            except (ConflictError, NotFoundError):
                continue
            if (port := web_port(entry.template, values)) is None:
                continue
            access = entry.template.access
            https = bool(access and (access.web or "").startswith("https"))
            out[app.id] = (app, zone, caddy.Site("", f"{app.slug}-{port[0]}-1:{port[1]}", https))
        return out

    async def _routes(self, session: AsyncSession) -> list[tuple[ProxyRoute, Application]]:
        rows = await session.execute(
            select(ProxyRoute, Application).join(Application, Application.id == ProxyRoute.app_id)
            .order_by(ProxyRoute.domain)
        )  # fmt: skip
        return [(r, a) for r, a in rows]

    async def _sync(self) -> None:
        """Rewrite the sites file and reload Caddy if it runs. Caller holds the lock."""
        async with self.sessions() as session:
            proxy = await self._proxy(session)
            if proxy is None:
                return
            targets = await self._targets(session, proxy)
            sites = [caddy.Site(r.domain, t[2].upstream, t[2].https)
                     for r, _ in await self._routes(session)
                     if (t := targets.get(r.app_id)) and t[1].slug in proxy.zones]  # fmt: skip
        text = caddy.sites_file(sites)
        before = None
        with suppress(OSError):
            before = proxy.sites.read_text()
        if before == text:
            return
        _write(proxy.sites, text)
        if proxy.container is None:
            return  # Caddy reads it on start
        code, out = await self.gateway.exec_run(
            proxy.container.id, ["caddy", "reload", "--config", proxy.spec.config]
        )
        if code != 0:
            _write(proxy.sites, before or caddy.sites_file([]))
            raise ProxyApplyError("Caddy refused the configuration", output=out[-500:])

    async def sync(self) -> None:
        async with self._lock:
            await self._sync()

    async def _join(self, zones: set[str]) -> Job | None:
        """The proxy joins these zones' networks (a new revision) if it does not yet;
        a zone whose apps had no network of their own gets one (redeployed)."""
        async with self.sessions() as session, session.begin():
            proxy = await self._proxy(session)
            if proxy is None or not (added := zones - set(proxy.zones)):
                return None
            linked = []
            for zone in await session.scalars(select(Zone).where(Zone.slug.in_(added))):
                if zone.network_mode is not NetworkMode.SHARED:
                    zone.network_mode = NetworkMode.SHARED
                    linked.append(zone.id)
        inputs = {**proxy.values, proxy.spec.zones_field: ",".join([*proxy.zones, *sorted(added)])}
        job = await self.apps.revisions.update(proxy.app_id, inputs)
        for zone_id in linked:
            await self.apps.revisions.redeploy_zone(zone_id)
        return job

    async def overview(self) -> dict[str, Any]:
        async with self.sessions() as session:
            proxy = await self._proxy(session)
            targets = await self._targets(session, proxy)
            routes = await self._routes(session)
        log: list[str] = []
        if proxy and proxy.container:
            with suppress(Exception):  # the list still shows; only the errors are missing
                log = [line async for line in self.gateway.logs(proxy.container.id, tail=1000)]
        errors = caddy.last_errors(log)
        ips = await asyncio.gather(*(self.resolver(r.domain) for r, _ in routes))
        public, now = self.public_ip(), self.clock.now()
        out = []
        for (r, app), addresses in zip(routes, ips, strict=True):
            cert = caddy.certificate(proxy.data, r.domain) if proxy else None
            error = errors.get(r.domain)
            target = targets.get(r.app_id)
            out.append({
                "id": r.id, "domain": r.domain, "app_id": app.id, "app_name": app.name,
                "zone": target[1].slug if target else None, "served": target is not None,
                "status": caddy.status(cert, error, now), "error": error,
                "expires_at": cert.expires_at if cert else None,
                "issuer": cert.issuer if cert else None,
                "dns": addresses, "points_here": bool(public) and public in addresses,
            })  # fmt: skip
        return {
            "installed": proxy is not None, "app_id": proxy.app_id if proxy else None,
            "running": bool(proxy and proxy.container), "public_ip": public, "routes": out,
            "targets": [{"id": a.id, "name": a.name, "zone": z.slug}
                        for a, z, _ in targets.values()],
        }  # fmt: skip

    async def create(self, domain: str, app_id: int) -> tuple[int, Job | None]:
        domain = caddy.check_domain(domain)
        async with self._lock:
            async with self.sessions() as session, session.begin():
                proxy = await self._proxy(session)
                if proxy is None:
                    raise ProxyNotInstalledError("install the HTTPS proxy first")
                target = (await self._targets(session, proxy)).get(app_id)
                if target is None:
                    raise ProxyTargetError(
                        "this app cannot be published: it needs a zone (not behind a VPN) "
                        "and a web port", field="app_id",
                    )  # fmt: skip
                if await session.scalar(select(ProxyRoute.id).where(ProxyRoute.domain == domain)):
                    raise ProxyDomainTakenError("this domain is already used", field="domain")
                route = ProxyRoute(domain=domain, app_id=app_id)
                session.add(route)
                await session.flush()
            job = await self._join({target[1].slug})
            if job is None:  # already on its network: Caddy serves it now
                await self._sync()
        self.bus.publish("proxy.domain_created", app=target[0].slug, target=domain)
        return route.id, job

    async def delete(self, rid: int) -> None:
        async with self._lock:
            async with self.sessions() as session, session.begin():
                route = await session.get(ProxyRoute, rid)
                if route is None:
                    raise ProxyRouteNotFoundError("unknown domain", id=rid)
                domain = route.domain
                await session.delete(route)
            await self._sync()
        self.bus.publish("proxy.domain_deleted", target=domain)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    tmp.replace(path)


async def follow_apps(proxy: ProxyTools) -> None:
    """After a deploy (the proxy's: its zones; an app's: its port) or a removal, rewrite
    the sites file; a proxy (re)installed joins the zones of the domains kept."""
    async with proxy.bus.subscribe("app.*") as sub:
        async for event in sub:
            if event.topic not in ("app.deployed", "app.removed"):
                continue
            await asyncio.sleep(3)  # ponytail: fixed wait for the state to see the container
            try:
                async with proxy.sessions() as session:
                    targets = await proxy._targets(session, await proxy._proxy(session))
                    zones = {targets[r.app_id][1].slug for r, _ in await proxy._routes(session)
                             if r.app_id in targets}  # fmt: skip
                async with proxy._lock:
                    if await proxy._join(zones) is None:
                        await proxy._sync()
            except Exception:
                logger.exception("proxy sites not applied", extra=event.payload)
