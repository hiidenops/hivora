"""The topology graph, computed server-side and sent as one JSON document.

Observed layer (never editable here): the host, zones, apps with their live
status and published ports, links from the Internet to publicly published
ports (Docker bypasses the host firewall), VPN apps reaching zones. Declared
layer: what the user draws. The analysis flags what deserves a look.
"""

import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.adoption import Adoption
from hivora.apps.core import latest_revision
from hivora.apps.models import Exposure, Origin
from hivora.apps.planner import AppPlanner
from hivora.apps.queries import apps_with_template
from hivora.hostfw.service import HostFirewall, listening
from hivora.sites.views import sites_by_host
from hivora.state import StateStore
from hivora.templates import Catalog
from hivora.templates.icons import IconCache
from hivora.topology.models import TopologyEdge, TopologyLayout, TopologyNode
from hivora.zones import NetworkMode, Zone

INTERNET = "internet"
FIREWALL = "firewall"
NO_ZONE = "zone:none"


@dataclass
class Graph:
    host: dict[str, Any]
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    positions: dict[str, dict[str, float | None]] = field(default_factory=dict)


class GraphBuilder:
    """Builds the graph from what it reads (no Runtime): the host's LAN address and public
    address, the database, the catalog, the apps' settings (planner), the host firewall,
    the live state, the icons, and the stacks Hivora could adopt."""

    def __init__(
        self, *, lan_ip: str | None, public_ip: Callable[[], str | None],
        sessions: async_sessionmaker[AsyncSession], catalog: Catalog, planner: AppPlanner,
        hostfw: HostFirewall, store: StateStore, icons: IconCache, adoption: Adoption,
    ) -> None:  # fmt: skip
        self.lan_ip = lan_ip
        self.public_ip = public_ip
        self.sessions = sessions
        self.catalog = catalog
        self.planner = planner
        self.hostfw = hostfw
        self.store = store
        self.icons = icons
        self.adoption = adoption

    async def build(self) -> Graph:
        host = {"name": socket.gethostname(), "arch": self.catalog.host_arch(),
                "lan_ip": self.lan_ip, "public_ip": self.public_ip()}  # fmt: skip
        graph = Graph(host=host)
        async with self.sessions() as session:
            zones = list(await session.scalars(select(Zone).order_by(Zone.sort_order, Zone.name)))
            with_template = await apps_with_template(session)  # by name
            apps = [app for app, _ in with_template]
            templates = {app.id: slug for app, slug in with_template}  # None: no template
            declared = list(await session.scalars(select(TopologyNode).order_by(TopologyNode.id)))
            links = list(await session.scalars(select(TopologyEdge).order_by(TopologyEdge.id)))
            hosted = await sites_by_host(session, self.lan_ip)  # nginx app id -> its sites
            graph.positions = {
                row.key: {"x": row.x, "y": row.y, "w": row.w, "h": row.h}
                for row in await session.scalars(select(TopologyLayout))
            }
            vpn_reach: dict[int, list[str]] = {}
            overridden: dict[int, dict[tuple[str, str], str]] = {}
            template_ports: dict[int, dict[tuple[str, int, str], str]] = {}
            for app in apps:
                template = templates.get(app.id)
                try:
                    spec = self.catalog.get(template).template if template else None
                except Exception:  # template gone from the catalog
                    spec = None
                vpn = spec.vpn if spec else None
                latest = await latest_revision(session, app.id)
                if spec:  # a port set by a form field: the exposure picked there
                    chosen = latest.inputs if latest else {}
                    template_ports[app.id] = {
                        (name, p.container, p.protocol):
                            chosen.get(p.exposure_field or "") or p.exposure
                        for name, svc in spec.services.items() for p in svc.ports
                    }  # fmt: skip
                if latest and latest.overrides:
                    overridden[app.id] = {
                        (name, key): value
                        for name, svc in (latest.overrides.get("services") or {}).items()
                        for key, value in (svc.get("publish") or {}).items()
                    }  # fmt: skip
                if vpn and vpn.zones_field:
                    values = (await self.planner.current_settings(session, app.id)).values
                    reached = str(values.get(vpn.zones_field) or "")
                    vpn_reach[app.id] = [z for z in reached.split(",") if z]

        graph.nodes.append({"key": INTERNET, "type": "internet", "label": "Internet"})
        # The host firewall sits between the Internet and the host (published Docker
        # ports go around it: their own edges from the Internet say so).
        try:
            fw = await self.hostfw.state()
            firewall: dict[str, Any] = {
                "agent": fw.agent, "ufw_installed": fw.ufw_installed, "ufw_active": fw.ufw_active,
                "ufw_rules": len(fw.ufw_rules), "fail2ban_installed": fw.fail2ban_installed,
                "fail2ban_running": fw.fail2ban_running, "jails": len(fw.jails),
                "banned": sum(len(j.banned) for j in fw.jails),
            }  # fmt: skip
            if fw.agent:  # ports reachable from outside the host right now
                rows = await listening(self.hostfw)
                firewall["open"] = sorted(
                    {r["port"] for r in rows if r["ufw"] != "local" and r["ufw"] != "blocked"}
                )
        except Exception as exc:  # agent unreachable: shown as such
            firewall = {"agent": True, "error": str(exc)[:200]}
        graph.nodes.append(
            {"key": FIREWALL, "type": "firewall", "label": "UFW / fail2ban", **firewall}
        )
        graph.edges.append({"source": INTERNET, "target": FIREWALL, "kind": "host", "label": ""})
        zone_key = {z.id: f"zone:{z.id}" for z in zones}
        by_slug = {z.slug: z for z in zones}
        for z in zones:
            graph.edges.append({"source": FIREWALL, "target": zone_key[z.id], "kind": "host",
                                "label": ""})  # fmt: skip
            graph.nodes.append({"key": zone_key[z.id], "type": "zone", "label": z.name,
                                "slug": z.slug, "color": z.color,
                                "network_mode": z.network_mode.value})  # fmt: skip
        if any(a.zone_id not in zone_key for a in apps):
            graph.nodes.append({"key": NO_ZONE, "type": "zone", "label": None, "slug": None,
                                "color": None, "network_mode": "none"})  # fmt: skip

        app_by_slug = {a.slug: a.id for a in apps}
        behind = {
            slug[1:] for reach in vpn_reach.values() for slug in reach if slug.startswith("@")
        }
        for app in apps:
            key = f"app:{app.id}"
            template = templates.get(app.id)
            status = self.store.app(app.slug).status.value
            overrides, defaults = overridden.get(app.id, {}), template_ports.get(app.id, {})
            ports = [  # unpublished ones too (port: the container's): they can be opened again
                {"port": p.host_port or p.container_port, "container": p.container_port,
                 "protocol": p.protocol, "service": svc.name,
                 "exposure": p.exposure.value if p.host_port else "internal",
                 # what the advanced settings force, and what the template does by itself
                 "override": overrides.get((svc.name, f"{p.container_port}/{p.protocol}")),
                 "default": defaults.get((svc.name, p.container_port, p.protocol))}
                for svc in app.services for p in svc.ports
            ]  # fmt: skip
            parent = zone_key.get(app.zone_id or -1, NO_ZONE)
            icon = (
                f"/api/v1/templates/{template}/icon"
                if template and self.icons.path(template)
                else None
            )
            graph.nodes.append({
                "key": key, "type": "app", "parent": parent, "id": app.id, "label": app.name,
                "slug": app.slug, "status": status, "icon_url": icon, "template": template,
                "origin": app.origin.value, "services": [s.name for s in app.services],
                "ports": ports, "vpn": app.id in vpn_reach, "behind_vpn": app.slug in behind,
                "vpn_address": _address_on(self.store, app.slug, f"{app.slug}_default")
                if app.slug in behind else None,
            })  # fmt: skip
            # The sites this nginx hosts: a node each, next to it (what a reverse proxy will
            # point at later), linked from the nginx.
            for site in hosted.get(app.id, []):
                site_key = f"site:{site.id}"
                graph.nodes.append({
                    "key": site_key, "type": "site", "parent": parent, "host": key, "id": site.id,
                    "app_id": app.id, "label": site.name, "slug": site.slug, "main": site.main,
                    "port": site.port, "server_name": site.server_name, "enabled": site.enabled,
                    "url": site.url,
                })  # fmt: skip
                graph.edges.append({"source": key, "target": site_key, "kind": "site",
                                    "label": f":{site.port}" if site.port else ""})  # fmt: skip
            public = [p for p in ports if p["exposure"] == Exposure.PUBLIC.value]
            for p in public:
                graph.edges.append({"source": INTERNET, "target": key, "kind": "exposed",
                                    "label": f"{p['port']}/{p['protocol']}"})  # fmt: skip
            if public:
                zone = next((z for z in zones if z.id == app.zone_id), None)
                isolated = zone is not None and zone.network_mode is NetworkMode.ISOLATED
                graph.alerts.append({
                    "level": "danger" if isolated else "warn",
                    "code": "isolated_public" if isolated else "public_port",
                    "target": key, "app": app.name,
                    "ports": ", ".join(f"{p['port']}/{p['protocol']}" for p in public),
                })  # fmt: skip
            closed = [
                p
                for p in ports
                if p["override"] == "none" and p["default"] not in (None, "internal")
            ]
            if closed and app.slug not in behind:  # closed by hand, no VPN to go through
                names = ", ".join(f"{p['container']}/{p['protocol']}" for p in closed)
                graph.alerts.append({"level": "warn", "code": "unreachable", "target": key,
                                     "app": app.name, "ports": names})  # fmt: skip
            if parent == NO_ZONE and app.origin is not Origin.ADOPTED:
                graph.alerts.append({"level": "info", "code": "no_zone", "target": key,
                                     "app": app.name})  # fmt: skip
            for slug in vpn_reach.get(app.id, []):
                if slug in by_slug:
                    graph.edges.append({"source": key, "target": zone_key[by_slug[slug].id],
                                        "kind": "vpn", "label": "VPN"})  # fmt: skip
                elif slug.startswith("@") and slug[1:] in app_by_slug:
                    graph.edges.append({"source": key, "target": f"app:{app_by_slug[slug[1:]]}",
                                        "kind": "vpn", "label": "VPN"})  # fmt: skip

        unmanaged = len(self.store.unmanaged()) + len(self.adoption.candidates())
        if unmanaged:
            graph.alerts.append({"level": "info", "code": "unmanaged", "target": None,
                                 "count": unmanaged})  # fmt: skip

        for n in declared:
            graph.nodes.append({"key": f"decl:{n.id}", "type": "declared", "id": n.id,
                                "kind": n.kind, "label": n.label})  # fmt: skip
        keys = {n["key"] for n in graph.nodes}
        for e in links:
            if e.source in keys and e.target in keys:  # a link to a removed app is left out
                graph.edges.append({"id": e.id, "source": e.source, "target": e.target,
                                    "kind": "declared", "label": e.label})  # fmt: skip
        return graph


def _address_on(store: StateStore, slug: str, network: str) -> str | None:
    """The app's main container address on one Docker network (what VPN clients use)."""
    for c in store.containers():
        if store.key_of(c) == slug and network in c.networks:
            ips = dict(zip(c.networks, c.ips, strict=False))
            if ip := ips.get(network):
                return ip
    return None
