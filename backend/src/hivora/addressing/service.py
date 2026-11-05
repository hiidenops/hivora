"""The addressing plan, kept in the database (intention): the Hivora range, each zone's
subnet, each app's own network and every container's address. Docker holds what is really
applied; ``overview`` shows both and the gap.

Allocation happens while an app is planned, in the caller's session: a preview's rows are
rolled back with it, a deploy's are committed with its revision.
"""

import ipaddress
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.addressing import plan as p
from hivora.addressing.models import AppNetwork, IpAssignment
from hivora.addressing.plan import Taken
from hivora.db.models import Setting
from hivora.docker_gateway import ContainerInfo, DockerGateway
from hivora.zones import Zone, list_zones, zone_network

RANGE_SETTING = "addressing.range"
ZONE_NETWORK_PREFIX = "hivora-zone-"
# Fixed by the installer (the same values in install.sh): the Administration zone, the
# panel's address in it and the administration VPN's tunnel. Never given to anything else.
ADMIN_ZONE_SUBNET = "10.254.254.0/24"
PANEL_IP = "10.254.254.254"
ADMIN_VPN_SUBNET = "10.254.253.0/24"  # not 10.8.0.0/24: a user's own VPN keeps it
ADMIN_NETWORKS = (Taken(ADMIN_ZONE_SUBNET, "zone:administration"),
                  Taken(ADMIN_VPN_SUBNET, "vpn:admin-vpn"))  # fmt: skip

# What else is taken, outside the plan: the host's own networks and routes, the networks
# of the VPNs (their tunnels). Given by the composition root (no hostfw nor vpn import).
TakenSource = Callable[[AsyncSession], Awaitable[list[Taken]]]


def default_network(slug: str) -> str:
    """The Docker name of an app's own network (Compose: ``<project>_default``)."""
    return f"{slug}_default"


@dataclass(frozen=True, slots=True)
class AppAddressing:
    """What the compiler writes for one app (``AppContext`` fields)."""

    default_subnet: str | None
    network_subnets: tuple[tuple[str, str], ...]
    addresses: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class AppRef:
    """What the overview needs of an app (given by the API: addressing never imports apps)."""

    id: int
    slug: str
    name: str
    zone_id: int | None


@dataclass(slots=True)
class Row:
    """One container's address in one network: planned, really applied, and the gap."""

    app_id: int | None
    app: str
    name: str
    service: str
    network: str
    planned: str
    actual: str | None
    manual: bool

    @property
    def state(self) -> str:
        if self.actual is None:
            return "pending"  # not applied yet (next deploy) or not running
        return "ok" if self.actual == self.planned else "drift"


def actual_addresses(containers: Iterable[ContainerInfo]) -> dict[tuple[str, str, str], str]:
    """(app slug, service, network) -> the address Docker gave, from the running state."""
    out = {}
    for c in containers:
        slug = c.labels.get("io.hivora.app") or c.labels.get("com.docker.compose.project")
        service = c.labels.get("com.docker.compose.service")
        if slug and service:
            for network, ip in zip(c.networks, c.ips, strict=False):
                out[(slug, service, network)] = ip
    return out


def _row_out(r: Row) -> dict[str, object]:
    return {"app_id": r.app_id, "app": r.app, "name": r.name, "service": r.service,
            "network": r.network, "planned": r.planned, "actual": r.actual,
            "manual": r.manual, "state": r.state}  # fmt: skip


class Addressing:
    def __init__(self, *, sessions: async_sessionmaker[AsyncSession],
                 gateway: DockerGateway | None) -> None:  # fmt: skip
        self.sessions = sessions
        self.gateway = gateway
        self.sources: list[TakenSource] = []

    # -- what is taken -------------------------------------------------------------------

    async def docker_taken(self) -> list[Taken]:
        """Docker networks that are not Hivora's (``docker0``, other stacks...)."""
        if self.gateway is None:
            return []
        out = []
        for n in await self.gateway.list_networks():
            if n.name.startswith(ZONE_NETWORK_PREFIX) or n.labels.get("io.hivora.app"):
                continue
            if "com.docker.compose.project" in n.labels and n.name.endswith("_default"):
                continue  # an app's own network: its plan is ours (Hivora's or adopted)
            out += [Taken(s, f"docker:{n.name}") for s in n.subnets]
        return out

    async def taken(self, session: AsyncSession, *, skip_zone: int | None = None,
                    skip_app: str | None = None, outside: bool = True) -> list[Taken]:  # fmt: skip
        """Every network already used: the plan's (zones, apps' own networks), the fixed
        administration ranges and, with ``outside``, Docker's others, the host's, the VPNs'."""
        out = list(ADMIN_NETWORKS)
        for z in await list_zones(session):
            if z.subnet and z.id != skip_zone:
                out.append(Taken(z.subnet, f"zone:{z.slug}"))
        for a in await session.scalars(select(AppNetwork)):
            if a.app != skip_app:
                out.append(Taken(a.subnet, f"app:{a.app}"))
        if outside:
            out += await self.docker_taken()
            for source in self.sources:
                out += await source(session)
        return out

    # -- the Hivora range ----------------------------------------------------------------

    async def hivora_range(self, session: AsyncSession) -> p.Net:
        """The range zones and apps' networks come from: picked once, then kept."""
        row = await session.get(Setting, RANGE_SETTING)
        if row is not None:
            return p.net(str(row.value))
        chosen = p.pick_range(await self.taken(session))
        session.add(Setting(key=RANGE_SETTING, value=str(chosen)))
        await session.flush()
        return chosen

    # -- zones ---------------------------------------------------------------------------

    async def zone_subnet(self, session: AsyncSession, zone: Zone,
                          vpn_subnet: str | None = None) -> str:  # fmt: skip
        """The zone's subnet, given now if it has none: next to the VPN's when one reaches
        it, else the next free /24 of the Hivora range."""
        if zone.subnet:
            return zone.subnet
        if zone.is_system:  # Administration: the installer's (its network, the panel's IP)
            zone.subnet = ADMIN_ZONE_SUBNET
            await session.flush()
            return zone.subnet
        taken = await self.taken(session, skip_zone=zone.id)
        if vpn_subnet:
            zone.subnet = str(p.next_to(vpn_subnet, taken))
        else:
            half = p.zones_half(await self.hivora_range(session))
            found = p.free_subnet([half], p.ZONE_PREFIX, taken)
            if found is None:
                raise p.NetworkFullError("no free /24 left in the Hivora range", range=str(half))
            zone.subnet = str(found)
        await session.flush()
        return zone.subnet

    async def follow_vpn(self, session: AsyncSession, zone: Zone, vpn_subnet: str) -> bool:
        """A VPN now reaches the zone: its subnet moves next to the VPN's, unless chosen by
        hand or already there. Returns whether it changed (the zone is redeployed anyway)."""
        if zone.is_system or zone.subnet_manual:
            return False
        vpn = p.net(vpn_subnet)
        if zone.subnet and _near(p.net(zone.subnet), vpn):
            return False
        zone.subnet = None
        await self.zone_subnet(session, zone, vpn_subnet)
        await self._drop_outside(session, zone_network_name(zone), zone.subnet)
        return True

    async def set_zone_subnet(self, session: AsyncSession, zone: Zone, value: str | None) -> str:
        """A subnet chosen by hand (None: back to an automatic one, given now)."""
        if value is None:
            zone.subnet, zone.subnet_manual = None, False
            subnet = await self.zone_subnet(session, zone)
        else:
            taken = await self.taken(session, skip_zone=zone.id)
            subnet = str(p.check_subnet(value, taken))
            zone.subnet, zone.subnet_manual = subnet, True
        # The apps' own /28 carved in it (zone without a shared network) follow it too.
        await self._drop_outside(session, zone_network_name(zone), subnet)
        await session.flush()
        return subnet

    async def set_range(self, session: AsyncSession, value: str,
                        requester: str | None = None) -> str:  # fmt: skip
        """A new Hivora range (a /16): the zones and apps' networks that came from the old
        one are given again from it (zones by hand, behind a VPN or Administration keep
        theirs). Every app then needs a redeploy to apply it."""
        old = await self.hivora_range(session)
        keep = [z for z in await list_zones(session) if z.is_system or z.subnet_manual
                or (z.subnet and not _in_range(z.subnet, old))]  # fmt: skip
        taken = [t for t in await self.taken(session)
                 if not t.owner.startswith(("zone:", "app:"))]  # fmt: skip
        taken += [Taken(z.subnet, f"zone:{z.slug}") for z in keep if z.subnet]
        if requester:
            taken.append(Taken(f"{requester}/32", "requester"))
        chosen = p.check_subnet(value, taken, prefixes=(16, 16))
        row = await session.get(Setting, RANGE_SETTING)
        if row is None:
            session.add(Setting(key=RANGE_SETTING, value=str(chosen)))
        else:
            row.value = str(chosen)
        kept = {z.id for z in keep}
        for z in await list_zones(session):
            if z.id not in kept:
                z.subnet = None
        await session.execute(delete(AppNetwork))
        await session.flush()
        for z in await list_zones(session):
            if z.id not in kept:
                await self.zone_subnet(session, z)
        return str(chosen)

    async def set_ip(self, session: AsyncSession, slug: str, service: str, network: str,
                     value: str | None) -> str | None:  # fmt: skip
        """A service's address chosen by hand in one of its networks (None: back to an
        automatic one, given on the next deploy)."""
        query = select(IpAssignment).where(IpAssignment.network == network)
        rows = list(await session.scalars(query))
        mine = next((r for r in rows if r.app == slug and r.service == service), None)
        if mine is None:
            raise p.AddressInvalidError("this service has no address in this network",
                                        app=slug, service=service, network=network)  # fmt: skip
        if value is None:
            await session.delete(mine)
            await session.flush()
            return None
        subnet = await self._subnet_of(session, network)
        if subnet is None:
            raise p.AddressInvalidError("this network has no planned subnet", network=network)
        used = {r.address: f"{r.app}/{r.service}" for r in rows if r is not mine}
        if subnet == ADMIN_ZONE_SUBNET:
            used[PANEL_IP] = "hivora"
        mine.address = p.check_address(value, p.net(subnet), used)
        mine.manual = True
        await session.flush()
        return mine.address

    async def joiners(self, session: AsyncSession, network: str) -> list[str]:
        """Slugs of the apps with an address in this network (its zone's apps and the ones
        joining it: a VPN, the HTTPS proxy, a linked tool)."""
        query = select(IpAssignment.app).where(IpAssignment.network == network).distinct()
        return list(await session.scalars(query))

    async def stale(self, session: AsyncSession, composes: dict[str, str]) -> list[str]:
        """Apps whose applied compose (slug -> its YAML) lacks a planned value: their next
        deploy applies the plan ("Apply the plan")."""
        nets = {a.app: a.subnet for a in await session.scalars(select(AppNetwork))}
        planned: dict[str, list[str]] = {}
        for r in await session.scalars(select(IpAssignment)):
            planned.setdefault(r.app, []).append(r.address)
        out = []
        for slug, text in composes.items():
            wanted = [*planned.get(slug, []), *([nets[slug]] if slug in nets else [])]
            if not wanted or any(v not in text for v in wanted):
                out.append(slug)
        return out

    # -- apps ----------------------------------------------------------------------------

    async def app_subnet(self, session: AsyncSession, slug: str, zone: Zone | None) -> str:
        """The app's own network: a /28 of its zone's /24 when the zone shares no network
        (apps kept apart, each in its piece of the zone), else of the Hivora range."""
        block = await self._app_block(session, zone)
        row = await session.get(AppNetwork, slug)
        if row is not None and p.net(row.subnet).subnet_of(block):
            return row.subnet
        taken = await self.taken(session, skip_app=slug, outside=False)
        # The zone's own subnet holds the /28: it is not "taken" for them.
        taken = [t for t in taken if not (zone and t.owner == f"zone:{zone.slug}")]
        found = p.free_subnet([block], p.APP_PREFIX, taken)
        if found is None:
            raise p.NetworkFullError("no free network left for this app", block=str(block),
                                     zone=zone.slug if zone else None)  # fmt: skip
        if row is None:
            session.add(AppNetwork(app=slug, subnet=str(found)))
        else:
            row.subnet = str(found)
            await self._drop_outside(session, default_network(slug), str(found))
        await session.flush()
        return str(found)

    async def _app_block(self, session: AsyncSession, zone: Zone | None) -> p.Net:
        if zone is not None and zone_network(zone) is None and not zone.is_system:
            return p.net(await self.zone_subnet(session, zone))
        return p.apps_half(await self.hivora_range(session))

    async def address(self, session: AsyncSession, network: str, subnet: str, slug: str,
                      service: str, first: int = 2) -> str:  # fmt: skip
        """The service's fixed address in this network: kept while it fits, else the next
        free one (from ``.first`` on)."""
        net = p.net(subnet)
        query = select(IpAssignment).where(IpAssignment.network == network)
        rows = list(await session.scalars(query))
        mine = next((r for r in rows if r.app == slug and r.service == service), None)
        if mine is not None and ipaddress.ip_address(mine.address) in net:
            return mine.address
        used = [r.address for r in rows if r is not mine]
        if subnet == ADMIN_ZONE_SUBNET:
            used.append(PANEL_IP)
        address = p.free_address(net, used, first)
        if mine is None:
            session.add(IpAssignment(network=network, app=slug, service=service, address=address))
        else:
            mine.address, mine.manual = address, False
        await session.flush()
        return address

    async def for_app(self, session: AsyncSession, slug: str, zone: Zone | None,
                      services: Iterable[str], joined: Iterable[str]) -> AppAddressing:  # fmt: skip
        """Every fixed value the app's compose needs: its own network, its zone's network
        and the ones it joins (``joined``: Docker network names), one address per service in
        each."""
        services = list(services)
        default_subnet = await self.app_subnet(session, slug, zone)
        networks: list[tuple[str, str, int]] = [("default", default_subnet, 2)]
        own = zone_network(zone)
        subnets: dict[str, str] = {}
        for name in [*([own] if own else []), *joined]:
            if name in subnets:
                continue
            subnet = await self._subnet_of(session, name)
            if subnet:
                subnets[name] = subnet
                networks.append((name, subnet, p.FIRST_HOST))
        addresses = []
        for network, subnet, first in networks:
            key = default_network(slug) if network == "default" else network
            for service in services:
                ip = await self.address(session, key, subnet, slug, service, first)
                addresses.append((network, service, ip))
        # Services gone from the template, networks left (another zone, a VPN no longer
        # reaching one): those addresses are free again.
        kept = [default_network(slug), *subnets]
        await session.execute(delete(IpAssignment).where(
            IpAssignment.app == slug,
            IpAssignment.service.not_in(services) | IpAssignment.network.not_in(kept)))  # fmt: skip
        return AppAddressing(default_subnet, tuple(subnets.items()), tuple(addresses))

    async def for_sidecar(self, session: AsyncSession, slug: str, service: str,
                          networks: Iterable[str]) -> dict[str, str]:  # fmt: skip
        """Fixed addresses of one of Hivora's own containers (not an app: the VPN's web
        proxy) in these networks; its addresses elsewhere are free again."""
        out = {}
        for network in networks:
            if subnet := await self._subnet_of(session, network):
                out[network] = await self.address(session, network, subnet, slug, service,
                                                  p.FIRST_HOST)  # fmt: skip
        await session.execute(delete(IpAssignment).where(
            IpAssignment.app == slug, IpAssignment.network.not_in(list(out))))  # fmt: skip
        return out

    async def _subnet_of(self, session: AsyncSession, network: str) -> str | None:
        """A network's planned subnet: a zone's, or an app's own (a tool joins it)."""
        if network.startswith(ZONE_NETWORK_PREFIX):
            for z in await list_zones(session):
                if zone_network(z) == network:
                    return await self.zone_subnet(session, z)
            return None
        if network.endswith("_default"):
            row = await session.get(AppNetwork, network.removesuffix("_default"))
            return row.subnet if row else None
        return None

    async def release(self, session: AsyncSession, slug: str) -> None:
        """The app is removed: its addresses and its network are free again."""
        await session.execute(delete(IpAssignment).where(IpAssignment.app == slug))
        await session.execute(delete(AppNetwork).where(AppNetwork.app == slug))
        await session.execute(delete(IpAssignment).where(
            IpAssignment.network == default_network(slug)))  # fmt: skip

    async def _drop_outside(self, session: AsyncSession, network: str | None,
                            subnet: str | None) -> None:  # fmt: skip
        """Addresses in a network that moved: those outside its new subnet are given again
        on the next deploy (hand-chosen ones too: they no longer fit)."""
        if not network or not subnet:
            return
        net = p.net(subnet)
        query = select(IpAssignment).where(IpAssignment.network == network)
        for row in await session.scalars(query):
            if ipaddress.ip_address(row.address) not in net:
                await session.delete(row)
        await session.flush()

    async def overview(self, session: AsyncSession, apps: list[AppRef],
                       containers: Iterable[ContainerInfo],
                       vpn_zones: dict[str, str]) -> dict[str, object]:  # fmt: skip
        """The plan and what Docker really applied, for the Addressing page.
        ``vpn_zones``: zone slug -> the name of the VPN that reaches it."""
        hivora_range = await self.hivora_range(session)
        by_slug = {a.slug: a for a in apps}
        actual = actual_addresses(containers)
        docker = (
            {n.name: n.subnets for n in await self.gateway.list_networks()} if self.gateway else {}
        )
        app_nets = {a.app: a.subnet for a in await session.scalars(select(AppNetwork))}
        rows: dict[str, list[Row]] = {}
        for r in await session.scalars(select(IpAssignment).order_by(IpAssignment.address)):
            ref = by_slug.get(r.app)
            rows.setdefault(r.network, []).append(Row(
                ref.id if ref else None, r.app, ref.name if ref else r.app, r.service, r.network,
                r.address, actual.get((r.app, r.service, r.network)), r.manual,
            ))  # fmt: skip
        zones = []
        for z in await list_zones(session):
            subnet = z.subnet
            origin = ("system" if z.is_system else "manual" if z.subnet_manual
                      else "vpn" if z.slug in vpn_zones else "range")  # fmt: skip
            shared = zone_network(z)
            members: list[Row] = []
            app_networks = []
            if shared:
                members = rows.get(shared, [])
            else:  # each app's own /28, carved in the zone's subnet
                for a in apps:
                    if a.zone_id == z.id and (own := app_nets.get(a.slug)):
                        app_networks.append({"app": a.slug, "name": a.name, "subnet": own})
                        members += rows.get(default_network(a.slug), [])
            net = p.net(subnet) if subnet else None
            zones.append({
                "slug": z.slug, "name": z.name, "color": z.color, "subnet": subnet,
                "network": shared, "mode": z.network_mode.value, "origin": origin,
                "vpn": vpn_zones.get(z.slug),
                "actual_subnets": list(docker.get(shared, ())) if shared else [],
                "size": (net.num_addresses - 3) if net else 0,
                "used": len({m.planned for m in members}),
                "app_networks": app_networks,
                "rows": [_row_out(m) for m in members],
            })  # fmt: skip
        own_rows = []  # apps' own networks outside any zone's subnet (the range's upper half)
        for a in apps:
            own = app_nets.get(a.slug)
            if own and p.net(own).subnet_of(p.apps_half(hivora_range)):
                for m in rows.get(default_network(a.slug), []):
                    own_rows.append(
                        {
                            **_row_out(m),
                            "subnet": own,
                            "actual_subnets": list(docker.get(default_network(a.slug), ())),
                        }
                    )
        outside = [t for t in await self.taken(session)
                   if not t.owner.startswith(("zone:", "app:"))]  # fmt: skip
        return {
            "range": str(hivora_range),
            "zones_block": str(p.zones_half(hivora_range)),
            "apps_block": str(p.apps_half(hivora_range)),
            "excluded": [{"network": t.network, "owner": t.owner} for t in outside],
            "zones": zones,
            "app_networks": own_rows,
        }

    async def fill_zones(self) -> None:
        """At start: every zone without a subnet gets one (zones from before static
        addressing; the next deploy of their apps applies it)."""
        async with self.sessions() as session, session.begin():
            for zone in await list_zones(session):
                if not zone.subnet:
                    await self.zone_subnet(session, zone)


def zone_network_name(zone: Zone) -> str:
    """The zone's network name, shared or not (its apps' /28 are in its subnet otherwise)."""
    return f"{ZONE_NETWORK_PREFIX}{zone.slug}"


def _near(zone: p.Net, vpn: p.Net) -> bool:
    """The zone is "next to" the VPN: in the same /16."""
    if vpn.prefixlen < 16:
        return zone.subnet_of(vpn)
    return zone.supernet(new_prefix=16) == vpn.supernet(new_prefix=16)


def _in_range(subnet: str, hivora_range: p.Net) -> bool:
    return p.net(subnet).subnet_of(hivora_range)
