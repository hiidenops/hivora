"""Application commands. Every mutation is recorded as intent, then run as a job."""

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.addressing import Addressing
from hivora.apps.adoption import Adoption
from hivora.apps.compose_edit import ComposeEdit
from hivora.apps.core import (
    LABEL_COMPOSE_SERVICE,
    decrypt_secrets,
    get_app,
    latest_revision,
)
from hivora.apps.core import (  # re-exported: imported from here by other modules
    AppNotFoundError as AppNotFoundError,
)
from hivora.apps.core import (  # re-exported: imported from here by other modules
    DeployRequest as DeployRequest,
)
from hivora.apps.core import (
    PortConflictError as PortConflictError,
)
from hivora.apps.core import (
    UnsupportedArchitectureError as UnsupportedArchitectureError,
)
from hivora.apps.core import (
    slugify as slugify,
)
from hivora.apps.custom_images import CustomImages
from hivora.apps.lifecycle import Deployer, Lifecycle
from hivora.apps.lifecycle import (  # re-exported: imported from here by other modules
    RemovalPlan as RemovalPlan,
)
from hivora.apps.models import (
    Application,
)
from hivora.apps.planner import AppPlanner
from hivora.apps.planner import (  # re-exported: imported from here by other modules
    DeployPlan as DeployPlan,
)
from hivora.apps.revisions import Revisions
from hivora.apps.revisions import (  # re-exported: imported from here by other modules
    UpdatePlan as UpdatePlan,
)
from hivora.compose_runner import ComposeRunner
from hivora.core.clock import Clock, SystemClock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.docker_gateway import ContainerInfo, ContainerState, DockerGateway
from hivora.images.registry import Registry
from hivora.jobs import JobQueue
from hivora.state import StateStore
from hivora.templates import (
    AppContext,
    Catalog,
    CatalogEntry,
    FormValues,
    HostInfo,
    compile_template,
)
from hivora.templates.models import TemplateVersion
from hivora.templates.overrides import Overrides
from hivora.zones import Zone, zone_network


def vars_of_host(host: HostInfo) -> dict[str, Any]:
    return {f: getattr(host, f) for f in host.__slots__}  # slots dataclass: no __dict__


class AppService:
    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        catalog: Catalog,
        runner: ComposeRunner,
        state: StateStore,
        jobs: JobQueue,
        box: SecretBox,
        bus: EventBus,
        clock: Clock | None = None,
    ) -> None:
        # Set by the composition root (Runtime), like the planner's secret settings, public
        # address and sites' ports: the job handlers' Docker gateway (image platforms).
        self.gateway: DockerGateway | None = None
        self.addressing: Addressing | None = None  # the addressing plan (released on removal)
        self.settings = settings
        self.sessions = sessions
        self.catalog = catalog
        self.runner = runner
        self.state = state
        self.jobs = jobs
        self.box = box
        self.bus = bus
        self.clock = clock or SystemClock()
        self.planner = AppPlanner(settings=settings, catalog=catalog, state=state, box=box,
                                  clock=self.clock)  # fmt: skip
        self.compose = ComposeEdit(settings=settings, sessions=sessions, runner=runner, state=state,
                                   jobs=jobs, box=box, bus=bus, clock=self.clock)  # fmt: skip
        self.adoption = Adoption(sessions=sessions, state=state, bus=bus, clock=self.clock)
        self.custom = CustomImages(sessions=sessions, catalog=catalog, clock=self.clock)
        self.deployer = Deployer(planner=self.planner, sessions=sessions, catalog=catalog,
                                 jobs=jobs, box=box, bus=bus, clock=self.clock)  # fmt: skip
        self.lifecycle = Lifecycle(planner=self.planner, sessions=sessions, settings=settings,
                                   runner=runner, state=state, jobs=jobs)  # fmt: skip
        self.revisions = Revisions(planner=self.planner, sessions=sessions, catalog=catalog,
                                   jobs=jobs, box=box, bus=bus, clock=self.clock,
                                   custom=self.custom, compose=self.compose)  # fmt: skip

    # Free images live in CustomImages; kept here for the image inspection route.
    @property
    def registry(self) -> Registry:
        return self.custom.registry

    def volumes_dir(self, slug: str) -> Path:
        return self.settings.volumes_root / slug

    # --- queries ------------------------------------------------------------
    async def main_container(self, session: AsyncSession, app_id: int) -> tuple[
        Application, CatalogEntry | None, ContainerInfo | None
    ]:  # fmt: skip
        """The app, its template and its running main-service container (if any)."""
        app = await get_app(session, app_id)
        template_slug = await session.scalar(
            select(TemplateVersion.slug).where(TemplateVersion.id == app.template_version_id)
        )
        entry = self.catalog.get(template_slug) if template_slug else None
        main = entry.template.main_service if entry else None
        running = [
            c for c in self.state.containers()
            if self.state.key_of(c) == app.slug and c.state is ContainerState.RUNNING
            and (main is None or c.labels.get(LABEL_COMPOSE_SERVICE) == main)
        ]  # fmt: skip
        return app, entry, running[0] if running else None

    async def access_of(
        self, session: AsyncSession, app: Application,
        vpn_zones: dict[str, tuple[str, str]] | None = None,
    ) -> dict[str, str]:  # fmt: skip
        """Connection addresses (web / game) for the latest revision's inputs.
        ``vpn_zones``: the planner's, when the caller already has it (a whole list)."""
        try:
            entry = await self.planner.entry_of(session, app)
        except (ConflictError, NotFoundError):
            return {}
        latest = await latest_revision(session, app.id)
        if latest is None:
            return {}
        zone = await session.get(Zone, app.zone_id) if app.zone_id else None
        if vpn_zones is None:
            vpn_zones = await self.planner.vpn_zones(session)
        vpn_zone = zone is not None and zone.slug in vpn_zones
        ctx = AppContext(slug=app.slug, name=app.name, revision=latest.number,
                         vpn_only=vpn_zone)  # fmt: skip
        form = FormValues(dict(latest.inputs))
        overrides = Overrides.model_validate(latest.overrides or {})
        host = self.planner.host
        compiled = compile_template(entry.template, ctx, host, form, self.settings.volumes_root,
                                    overrides)  # fmt: skip
        access = dict(compiled.access)
        # Same addresses on the local network, when they differ (e.g. public IP vs LAN).
        lan_host = HostInfo(**{**vars_of_host(host), "public_ip": None})
        local = compile_template(
            entry.template, ctx, lan_host, form, self.settings.volumes_root, overrides
        ).access
        for key, value in local.items():
            if access.get(key) != value:
                access[f"{key}_lan"] = value
        # The ports really published (what the topology shows): a compose written by hand
        # may publish another host port than the form's, or none.
        real = {(svc.name, p.container_port, p.protocol): p.host_port
                for svc in app.services for p in svc.ports}  # fmt: skip
        moved: dict[int, int | None] = {}  # the template's host port -> the real one
        to_container: dict[int, int] = {}
        # The form's host port -> the container's, as the template maps them (in a VPN zone
        # nothing is published: the mapping comes from the template as if it were).
        mapped = compiled if not vpn_zone else compile_template(
            entry.template, replace(ctx, vpn_only=False), host, form, self.settings.volumes_root,
            overrides,
        )  # fmt: skip
        for svc in mapped.services:
            for p in svc.ports:
                if p.host_port:
                    to_container[p.host_port] = p.container_port
                    moved[p.host_port] = real.get((svc.name, p.container_port, p.protocol))
        published = {h for h in real.values() if h}
        for key, value in list(access.items()):
            m = re.search(r":(\d{1,5})(?=/|$)", value)
            if m and (now := moved.get(int(m.group(1)))) and now != int(m.group(1)):
                access[key] = f"{value[: m.start(1)]}{now}{value[m.end(1) :]}"
        # A port not published has no host address; in a zone a VPN reaches, the app is
        # reached at its own address on the zone's network (the container's port).
        hostport = re.compile(r"[\w.\-\[\]]+:(\d{1,5})(?=/|$)")
        unpublished = {
            key: value for key, value in access.items()
            if (m := hostport.search(value)) and int(m.group(1)) not in published
        }  # fmt: skip
        for key in unpublished:
            access.pop(key)
        if unpublished and vpn_zone:
            ip = next((ip for c in self.state.containers() if self.state.key_of(c) == app.slug
                       for net, ip in zip(c.networks, c.ips, strict=False)
                       if net == zone_network(zone)), None)  # fmt: skip
            if ip:  # same address form (http://...), the app's own IP and container port
                for key, value in unpublished.items():
                    if not key.endswith("_lan"):
                        port = int(hostport.search(value).group(1))  # type: ignore[union-attr]
                        access[f"{key}_vpn"] = hostport.sub(
                            f"{ip}:{to_container.get(port, port)}", value, count=1
                        )
        return access

    @staticmethod
    async def apps_per_zone(session: AsyncSession) -> dict[int, int]:
        rows = await session.execute(
            select(Application.zone_id, func.count()).group_by(Application.zone_id)
        )
        return {zid: n for zid, n in rows if zid is not None}

    # --- deploy, lifecycle, removal -------------------------------------------

    # --- used by the job handlers and backups (they hold the AppService, not apps.core)
    async def get(self, session: AsyncSession, app_id: int) -> Application:
        return await get_app(session, app_id)

    async def decrypt_secrets(self, session: AsyncSession, app_id: int) -> dict[str, str]:
        return await decrypt_secrets(session, self.box, app_id)
