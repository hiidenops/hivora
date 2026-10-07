"""Application commands. Every mutation is recorded as intent, then run as a job."""

import re
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from hivora.apps.planner import AppPlanner, AppSettings
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
from hivora.images.registry import ImageInfo, Registry
from hivora.jobs import Job, JobQueue
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

    # Free images live in CustomImages; kept here for the API and the tests.
    @property
    def registry(self) -> Registry:
        return self.custom.registry

    @registry.setter
    def registry(self, value: Registry) -> None:
        self.custom.registry = value

    @property
    def _inspected(self) -> dict[str, tuple[float, ImageInfo]]:
        return self.custom.inspected

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

    async def access_of(self, session: AsyncSession, app: Application) -> dict[str, str]:
        """Connection addresses (web / game) for the latest revision's inputs."""
        try:
            entry = await self.planner.entry_of(session, app)
        except (ConflictError, NotFoundError):
            return {}
        latest = await latest_revision(session, app.id)
        if latest is None:
            return {}
        ctx = AppContext(slug=app.slug, name=app.name, revision=latest.number)
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
        # A port no longer published (advanced settings) has no host address; behind a
        # VPN, the app is reached at its own address on its network, by VPN clients.
        published = {p.host_port for svc in compiled.services for p in svc.ports if p.host_port}
        unpublished = {
            key: m.group(1) for key, value in access.items()
            if (m := re.search(r":(\d{1,5})(?:/|$)", value)) and int(m.group(1)) not in published
        }  # fmt: skip
        for key in unpublished:
            access.pop(key)
        if unpublished and await self.planner.vpns_reaching(session, app.slug):
            ip = next((ip for c in self.state.containers() if self.state.key_of(c) == app.slug
                       for net, ip in zip(c.networks, c.ips, strict=False)
                       if net == f"{app.slug}_default"), None)  # fmt: skip
            if ip:
                for key, port in unpublished.items():
                    if not key.endswith("_lan"):
                        access[f"{key}_vpn"] = f"{ip}:{port}"
        return access

    @staticmethod
    async def apps_per_zone(session: AsyncSession) -> dict[int, int]:
        rows = await session.execute(
            select(Application.zone_id, func.count()).group_by(Application.zone_id)
        )
        return {zid: n for zid, n in rows if zid is not None}

    # --- deploy, lifecycle, removal -------------------------------------------

    # --- kept for the tests only: the code calls the sub-services (planner, deployer,
    # lifecycle, revisions, custom) and apps.core directly; to remove with the tests' calls.
    async def get(self, session: AsyncSession, app_id: int) -> Application:
        return await get_app(session, app_id)

    async def decrypt_secrets(self, session: AsyncSession, app_id: int) -> dict[str, str]:
        return await decrypt_secrets(session, self.box, app_id)

    async def current_settings(self, session: AsyncSession, app_id: int) -> AppSettings:
        return await self.planner.current_settings(session, app_id)

    async def plan_update(
        self, session: AsyncSession, app_id: int, inputs: dict[str, Any],
        entry: CatalogEntry | None = None, overrides: Overrides | None = None,
    ) -> UpdatePlan:  # fmt: skip
        return await self.revisions.plan_update(session, app_id, inputs, entry, overrides)

    async def update(
        self, app_id: int, inputs: dict[str, Any], *, reset_data: bool = False,
        entry: CatalogEntry | None = None, event: str = "app.updated",
        overrides: Overrides | None = None,
    ) -> Job:  # fmt: skip
        return await self.revisions.update(app_id, inputs, reset_data=reset_data, entry=entry,
                                           event=event, overrides=overrides)  # fmt: skip

    async def load_custom_templates(self) -> None:
        await self.custom.load_templates()

    async def plan_deploy(self, session: AsyncSession, req: DeployRequest) -> DeployPlan:
        return await self.deployer.plan_deploy(session, req)

    async def deploy(self, req: DeployRequest) -> tuple[Application, Job]:
        return await self.deployer.deploy(req)

    async def start(self, app_id: int) -> Job:
        return await self.lifecycle.start(app_id)

    async def stop(self, app_id: int) -> Job:
        return await self.lifecycle.stop(app_id)

    async def removal_plan(self, app_id: int) -> RemovalPlan:
        return await self.lifecycle.removal_plan(app_id)

    async def remove(self, app_id: int, *, remove_data: bool = False) -> Job:
        return await self.lifecycle.remove(app_id, remove_data=remove_data)
