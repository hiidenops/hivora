"""Application commands. Every mutation is recorded as intent, then run as a job."""

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.adoption import Adoption, Candidate
from hivora.apps.compose_edit import ComposeEdit, ComposePlan
from hivora.apps.core import (
    LABEL_COMPOSE_SERVICE,
    AppPlanner,
    AppSettings,
    conflict_dict,
    decrypt_secrets,
    get_app,
    latest_revision,
    queue_revision,
    services_from,
    store_secrets,
)
from hivora.apps.core import (  # re-exported: imported from here by other modules
    AppNotFoundError as AppNotFoundError,
)
from hivora.apps.core import (  # re-exported: imported from here by other modules
    DeployPlan as DeployPlan,
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
from hivora.apps.files import tree_size
from hivora.apps.models import (
    Application,
    AppRevision,
    AppSecret,
    DesiredState,
    Origin,
    RevisionStatus,
)
from hivora.compose_runner import ComposeRunner
from hivora.core.clock import Clock, SystemClock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.docker_gateway import ContainerInfo, ContainerState, DockerGateway
from hivora.images.registry import ImageInfo, Registry
from hivora.jobs import Job, JobKind, JobQueue
from hivora.state import StateStore, app_key
from hivora.system.secrets import SecretSettings
from hivora.templates import (
    AppContext,
    Catalog,
    CatalogEntry,
    FormValues,
    HostInfo,
    compile_template,
    host_arch,
)
from hivora.templates.catalog import CUSTOM_SOURCE, TemplateInvalidError, parse_template
from hivora.templates.custom import CustomEnv, CustomPort
from hivora.templates.models import TemplateVersion
from hivora.templates.overrides import Overrides
from hivora.zones import Zone, get_zone


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    plan: DeployPlan
    number: int  # the revision this change would create
    diff: str  # unified diff against the latest revision's compose
    # Fields flagged `reset_data_on_change` whose value changed: applying wipes
    # the volumes below (host path -> top-level names kept), after confirmation.
    reset_fields: list[str] = field(default_factory=list)
    reset_volumes: dict[str, list[str]] = field(default_factory=dict)
    reset_size: int = 0  # bytes currently stored in those volumes
    replaces_custom: bool = False  # the current compose was written by hand: it goes away


class DataResetRequiredError(ConflictError):
    code = "data_reset_required"


class RevisionNotRestorableError(ConflictError):
    code = "revision_not_restorable"


@dataclass(frozen=True, slots=True)
class UpgradeStatus:
    kind: Literal["template", "image"]  # newer template version / newer free-image digest
    current: str
    latest: str
    available: bool


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    slug: str
    containers: list[str]
    files: list[str]  # compose.yaml, .env: always removed
    data: list[str]  # bind-mounted data: removed only on explicit request


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
        secret_settings: SecretSettings | None = None,
        public_address: Callable[[], str | None] | None = None,
        gateway: DockerGateway | None = None,  # registry lookups (image platforms)
        registry: Registry | None = None,
    ) -> None:
        self.gateway = gateway
        self.settings = settings
        self.sessions = sessions
        self.catalog = catalog
        self.runner = runner
        self.state = state
        self.jobs = jobs
        self.box = box
        self.bus = bus
        self.clock = clock or SystemClock()
        self.secret_settings = secret_settings
        self.public_address = public_address
        self.planner = AppPlanner(settings=settings, catalog=catalog, state=state, box=box,
                                  clock=self.clock, secret_settings=secret_settings,
                                  public_address=public_address)  # fmt: skip
        self.compose = ComposeEdit(settings=settings, sessions=sessions, runner=runner, state=state,
                                   jobs=jobs, box=box, bus=bus, clock=self.clock)  # fmt: skip
        self.adoption = Adoption(sessions=sessions, state=state, bus=bus, clock=self.clock)
        self.custom = CustomImages(sessions=sessions, catalog=catalog, clock=self.clock,
                                   registry=registry)  # fmt: skip

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

    @property
    def host(self) -> HostInfo:
        return self.planner.host

    def volumes_dir(self, slug: str) -> Path:
        return self.settings.volumes_root / slug

    # --- queries ------------------------------------------------------------
    async def get(self, session: AsyncSession, app_id: int) -> Application:
        return await get_app(session, app_id)

    async def decrypt_secrets(self, session: AsyncSession, app_id: int) -> dict[str, str]:
        return await decrypt_secrets(session, self.box, app_id)

    # --- deploy -------------------------------------------------------------
    async def plan_deploy(self, session: AsyncSession, req: DeployRequest) -> DeployPlan:
        entry = self.catalog.get(req.template)
        if not entry.supports(host_arch()):
            raise UnsupportedArchitectureError(entry.slug, arch=host_arch())
        name = req.name.strip() or entry.template.metadata.name
        slug = req.slug or await self._free_slug(session, slugify(name))
        if req.slug and await session.scalar(
            select(Application.id).where(Application.slug == slug)
        ):
            raise ConflictError("slug already used", slug=slug)
        zone = await get_zone(session, req.zone) if req.zone else None
        return await self.planner.plan(session, entry, slug, name, zone, req.inputs, revision=1)

    async def main_container(self, session: AsyncSession, app_id: int) -> tuple[
        Application, CatalogEntry | None, ContainerInfo | None
    ]:  # fmt: skip
        """The app, its template and its running main-service container (if any)."""
        app = await self.get(session, app_id)
        template_slug = await session.scalar(
            select(TemplateVersion.slug).where(TemplateVersion.id == app.template_version_id)
        )
        entry = self.catalog.get(template_slug) if template_slug else None
        main = entry.template.main_service if entry else None
        running = [
            c for c in self.state.containers()
            if app_key(c) == app.slug and c.state is ContainerState.RUNNING
            and (main is None or c.labels.get(LABEL_COMPOSE_SERVICE) == main)
        ]  # fmt: skip
        return app, entry, running[0] if running else None

    async def access_of(self, session: AsyncSession, app: Application) -> dict[str, str]:
        """Connection addresses (web / game) for the latest revision's inputs."""
        try:
            entry = await self.planner.entry_of(session, app)
        except (ConflictError, NotFoundError):
            return {}
        latest = await self._latest_revision(session, app.id)
        if latest is None:
            return {}
        ctx = AppContext(slug=app.slug, name=app.name, revision=latest.number)
        form = FormValues(dict(latest.inputs))
        overrides = Overrides.model_validate(latest.overrides or {})
        host = self.host
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
        if unpublished and await self.vpns_reaching(session, app.slug):
            ip = next((ip for c in self.state.containers() if app_key(c) == app.slug
                       for net, ip in zip(c.networks, c.ips, strict=False)
                       if net == f"{app.slug}_default"), None)  # fmt: skip
            if ip:
                for key, port in unpublished.items():
                    if not key.endswith("_lan"):
                        access[f"{key}_vpn"] = f"{ip}:{port}"
        return access

    # --- settings (new revision) --------------------------------------------
    async def current_settings(self, session: AsyncSession, app_id: int) -> AppSettings:
        return await self.planner.current_settings(session, app_id)

    async def plan_update(
        self, session: AsyncSession, app_id: int, inputs: dict[str, Any],
        entry: CatalogEntry | None = None, overrides: Overrides | None = None,
    ) -> UpdatePlan:  # fmt: skip
        """Preview a settings change: new compose, its diff, port conflicts.

        Secret fields left empty keep their current value. ``entry``: another
        template version (upgrade, restore); default: the catalog's.
        """
        app = await self.get(session, app_id)
        entry = entry or await self.planner.entry_of(session, app)
        current = await self.decrypt_secrets(session, app.id)
        fields = {f.id for f in entry.template.form.fields}
        kept = {k: v for k, v in current.items() if not inputs.get(k) and k in fields}
        latest = await self._latest_revision(session, app.id)
        number = (latest.number if latest else 0) + 1
        zone = await session.get(Zone, app.zone_id) if app.zone_id else None
        if overrides is None:  # unchanged: the latest revision's advanced settings
            overrides = Overrides.model_validate(latest.overrides or {}) if latest else None
        plan = await self.planner.plan(session, entry, app.slug, app.name, zone, {**inputs, **kept},
                                revision=number, overrides=overrides)  # fmt: skip
        previous = latest.compose_yaml if latest else ""
        new = plan.compiled.compose_yaml
        diff = "".join(difflib.unified_diff(
            previous.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"revision {number - 1}", tofile=f"revision {number}",
        ))  # fmt: skip
        # Compare with the revision the data was produced by (the applied one),
        # not a failed attempt after it.
        applied = (
            await session.get(AppRevision, app.current_revision_id)
            if app.current_revision_id else latest
        )  # fmt: skip
        before = dict(applied.inputs) if applied else {}
        reset_fields = [
            f.id for f in entry.template.form.fields
            if f.reset_data_on_change and f.id in before
            and before[f.id] != plan.form.values.get(f.id)
        ]  # fmt: skip
        custom = bool(latest and latest.custom_compose)
        if not reset_fields:
            return UpdatePlan(plan, number, diff, replaces_custom=custom)
        # The template's volumes only: extra folders (advanced settings) are the user's own.
        keep = {(n, v.name): v.reset_keep for n, sp in entry.template.services.items()
                for v in sp.volumes}  # fmt: skip
        reset_volumes = {
            str(v.source): keep[(v.service, v.name)]
            for svc in plan.compiled.services for v in svc.volumes
            if not v.read_only and (v.service, v.name) in keep
        }  # fmt: skip
        size = sum(tree_size(Path(p)) for p in reset_volumes)
        return UpdatePlan(plan, number, diff, reset_fields, reset_volumes, size,
                          replaces_custom=custom)  # fmt: skip

    async def update(
        self, app_id: int, inputs: dict[str, Any], *, reset_data: bool = False,
        entry: CatalogEntry | None = None, event: str = "app.updated",
        overrides: Overrides | None = None,
    ) -> Job:  # fmt: skip
        async with self.sessions() as session, session.begin():
            upd = await self.plan_update(session, app_id, inputs, entry, overrides)
            plan = upd.plan
            if upd.reset_fields and not reset_data:
                raise DataResetRequiredError(
                    "this change erases the app data and must be confirmed",
                    fields=upd.reset_fields,
                )
            if plan.conflicts:
                raise PortConflictError(
                    "host ports already in use",
                    conflicts=[conflict_dict(c) for c in plan.conflicts],
                )
            app = await self.get(session, app_id)
            version = await self.planner.template_version(session, plan.entry)
            app.template_version_id = version.id
            await session.execute(delete(AppSecret).where(AppSecret.app_id == app.id))
            store_secrets(session, self.box, app.id, plan.form.secrets)
            revision = AppRevision(
                app_id=app.id, number=upd.number, inputs=plan.form.values,
                compose_yaml=plan.compiled.compose_yaml, diff_from_previous=upd.diff,
                template_version_id=version.id,
                overrides=plan.overrides.model_dump(exclude_defaults=True) or None,
                created_at=self.clock.now(), status=RevisionStatus.PENDING,
            )  # fmt: skip
            job = await queue_revision(
                session, self.jobs, app, revision, services_from(plan.compiled),
                {"reset_volumes": upd.reset_volumes} if upd.reset_fields else None,
            )  # fmt: skip
        self.jobs.wake()
        self.bus.publish(event, app=app.slug, revision=upd.number, job=job.id)
        return job

    # --- upgrade to the newest template / image, restore a revision ---------
    async def upgrade_status(self, session: AsyncSession, app_id: int) -> UpgradeStatus:
        """Is a newer template version (or, for a free image, a newer image) available?"""
        app = await self.get(session, app_id)
        current = await session.get(TemplateVersion, app.template_version_id)
        entry = await self.planner.entry_of(session, app)
        if current is None:  # pragma: no cover - every template app has one
            raise ConflictError("this app has no template version", slug=app.slug)
        if entry.source != CUSTOM_SOURCE:
            latest = entry.template.metadata.version
            return UpgradeStatus("template", current.version, latest, latest != current.version)
        return UpgradeStatus("image", *await self.custom.image_status(entry))

    async def _upgrade_entry(self, session: AsyncSession, app: Application) -> CatalogEntry:
        """The entry an upgrade applies: the catalog's, or the free image re-pinned."""
        entry = await self.planner.entry_of(session, app)
        return entry if entry.source != CUSTOM_SOURCE else await self.custom.repin(entry)

    async def plan_upgrade(self, session: AsyncSession, app_id: int) -> UpdatePlan:
        app = await self.get(session, app_id)
        entry = await self._upgrade_entry(session, app)
        values = (await self.current_settings(session, app_id)).values
        return await self.plan_update(session, app_id, values, entry)

    async def upgrade(self, app_id: int, *, reset_data: bool = False) -> Job:
        async with self.sessions() as session:
            app = await self.get(session, app_id)
            entry = await self._upgrade_entry(session, app)
            values = (await self.current_settings(session, app_id)).values
        job = await self.update(app_id, values, reset_data=reset_data, entry=entry,
                                event="app.upgraded")  # fmt: skip
        if entry.source == CUSTOM_SOURCE:
            self.catalog.add_custom(entry.manifest)  # the new pin becomes the app's template
        return job

    async def _revision_entry(self, session: AsyncSession, app_id: int,
                              number: int) -> tuple[AppRevision, CatalogEntry]:  # fmt: skip
        rev = await session.scalar(
            select(AppRevision).where(AppRevision.app_id == app_id, AppRevision.number == number)
        )
        if rev is None:
            raise NotFoundError("no such revision", revision=number)
        if rev.template_version_id is None:
            raise RevisionNotRestorableError("this revision predates restore support",
                                             revision=number)  # fmt: skip
        tv = await session.get_one(TemplateVersion, rev.template_version_id)
        try:
            template = parse_template(tv.manifest, require_pinned=False)
        except TemplateInvalidError as exc:
            raise RevisionNotRestorableError("its template no longer loads",
                                             revision=number) from exc  # fmt: skip
        return rev, CatalogEntry(template, tv.manifest, tv.checksum, tv.source)

    async def plan_restore(self, session: AsyncSession, app_id: int, number: int) -> UpdatePlan:
        rev, entry = await self._revision_entry(session, app_id, number)
        return await self.plan_update(session, app_id, dict(rev.inputs), entry,
                                      Overrides.model_validate(rev.overrides or {}))  # fmt: skip

    async def restore(self, app_id: int, number: int, *, reset_data: bool = False) -> Job:
        """A new revision with the settings and template version of revision ``number``."""
        async with self.sessions() as session:
            rev, entry = await self._revision_entry(session, app_id, number)
            inputs, overrides = dict(rev.inputs), Overrides.model_validate(rev.overrides or {})
            custom = rev.compose_yaml if rev.custom_compose else None
        if custom is not None:  # a hand-written compose comes back as it was
            return await self.apply_compose(app_id, custom, event="app.restored")
        job = await self.update(app_id, inputs, reset_data=reset_data, entry=entry,
                                event="app.restored", overrides=overrides)  # fmt: skip
        if entry.source == CUSTOM_SOURCE:
            self.catalog.add_custom(entry.manifest)  # that pin is the app's template again
        return job

    # --- adoption of existing compose stacks ------------------------------------
    def candidates(self) -> list[Candidate]:
        return self.adoption.candidates()

    async def adopt(self, project: str, name: str, zone_slug: str | None) -> Application:
        return await self.adoption.adopt(project, name, zone_slug)

    async def load_adopted(self) -> None:
        await self.adoption.load()

    # --- hand-written compose (admin) ------------------------------------------
    async def plan_compose(self, session: AsyncSession, app_id: int,
                           compose_yaml: str) -> ComposePlan:  # fmt: skip
        return await self.compose.plan(session, app_id, compose_yaml)

    async def apply_compose(self, app_id: int, compose_yaml: str, *,
                            event: str = "app.compose_edited") -> Job:  # fmt: skip
        return await self.compose.apply(app_id, compose_yaml, event=event)

    # --- free images (any registry image, through a generated template) -------
    async def custom_request(
        self, name: str, image: str, zone: str | None, ports: list[CustomPort],
        volumes: list[str], env: list[CustomEnv],
    ) -> DeployRequest:  # fmt: skip
        return await self.custom.request(name, image, zone, ports, volumes, env)

    async def load_custom_templates(self) -> None:
        await self.custom.load_templates()

    async def move_zone(self, app_id: int, zone_slug: str | None) -> Job:
        """Put the app in another zone (or none): a new revision joins the zone's network."""
        async with self.sessions() as session, session.begin():
            app = await self.get(session, app_id)
            zone = await get_zone(session, zone_slug) if zone_slug else None
            app.zone_id = zone.id if zone else None
        async with self.sessions() as session:
            values = (await self.current_settings(session, app_id)).values
        job = await self.update(app_id, values)
        self.bus.publish("app.zone_changed", app=app.slug, zone=zone_slug)
        return job

    @staticmethod
    async def apps_per_zone(session: AsyncSession) -> dict[int, int]:
        rows = await session.execute(
            select(Application.zone_id, func.count()).group_by(Application.zone_id)
        )
        return {zid: n for zid, n in rows if zid is not None}

    async def redeploy_zone(self, zone_id: int) -> list[Job]:
        """A zone's network changed: every app in it gets a new revision."""
        async with self.sessions() as session:
            ids = list(
                await session.scalars(select(Application.id).where(Application.zone_id == zone_id))
            )
        jobs = []
        for app_id in ids:
            async with self.sessions() as session:
                values = (await self.current_settings(session, app_id)).values
            jobs.append(await self.update(app_id, values))
        return jobs

    @staticmethod
    async def _latest_revision(session: AsyncSession, app_id: int) -> AppRevision | None:
        return await latest_revision(session, app_id)

    async def deploy(self, req: DeployRequest) -> tuple[Application, Job]:
        async with self.sessions() as session, session.begin():
            plan = await self.plan_deploy(session, req)
            if plan.conflicts:
                raise PortConflictError(
                    "host ports already in use",
                    conflicts=[conflict_dict(c) for c in plan.conflicts],
                )
            version = await self.planner.template_version(session, plan.entry)
            app = Application(
                slug=plan.slug, name=plan.name, zone_id=plan.zone.id if plan.zone else None,
                origin=Origin.TEMPLATE, template_version_id=version.id,
                desired_state=DesiredState.RUNNING, icon=None,
                notes="", created_at=self.clock.now(), services=services_from(plan.compiled),
            )  # fmt: skip
            session.add(app)
            await session.flush()
            store_secrets(session, self.box, app.id, plan.form.secrets)
            revision = AppRevision(
                app_id=app.id, number=1, inputs=plan.form.values,
                compose_yaml=plan.compiled.compose_yaml, created_at=self.clock.now(),
                template_version_id=version.id,
                status=RevisionStatus.PENDING,
            )  # fmt: skip
            session.add(revision)
            await session.flush()
            job = self.jobs.add(
                session,
                JobKind.DEPLOY,
                app_id=app.id,
                app_slug=app.slug,
                params={"revision_id": revision.id},
            )
        self.jobs.wake()
        self.bus.publish("app.created", app=app.slug, template=plan.entry.slug, job=job.id)
        return app, job

    # --- lifecycle ----------------------------------------------------------
    async def start(self, app_id: int) -> Job:
        return await self._lifecycle(app_id, JobKind.START, DesiredState.RUNNING)

    async def stop(self, app_id: int) -> Job:
        return await self._lifecycle(app_id, JobKind.STOP, DesiredState.STOPPED)

    async def restart(self, app_id: int) -> Job:
        return await self._lifecycle(app_id, JobKind.RESTART, DesiredState.RUNNING)

    async def removal_plan(self, app_id: int) -> RemovalPlan:
        async with self.sessions() as session:
            app = await self.get(session, app_id)
        if app.origin is Origin.ADOPTED:  # forgotten only: its containers keep running
            return RemovalPlan(slug=app.slug, containers=[], files=[], data=[])
        project = self.runner.project_dir(app.slug)
        data = self.volumes_dir(app.slug)
        return RemovalPlan(
            slug=app.slug,
            containers=sorted(c.name for c in self.state.app(app.slug).containers),
            files=[str(p) for p in sorted(project.glob("*"))] if project.exists() else [],
            data=[str(data)] if data.exists() else [],
        )

    async def vpns_reaching(self, session: AsyncSession, slug: str) -> list[str]:
        return await self.planner.vpns_reaching(session, slug)

    async def remove(self, app_id: int, *, remove_data: bool = False) -> Job:
        async with self.sessions() as session, session.begin():
            app = await self.get(session, app_id)
            if vpns := await self.vpns_reaching(session, app.slug):
                raise ConflictError("this app is behind a VPN: detach it from the VPN first",
                                    vpn=", ".join(vpns))  # fmt: skip
            job = self.jobs.add(
                session,
                JobKind.REMOVE,
                app_id=app.id,
                app_slug=app.slug,
                params={"remove_data": remove_data},
            )
        self.jobs.wake()
        return job

    async def _lifecycle(self, app_id: int, kind: JobKind, desired: DesiredState) -> Job:
        async with self.sessions() as session, session.begin():
            app = await self.get(session, app_id)
            if app.current_revision_id is None and app.origin is not Origin.ADOPTED:
                raise ConflictError("app has never been deployed", slug=app.slug)
            app.desired_state = desired
            job = self.jobs.add(session, kind, app_id=app.id, app_slug=app.slug)
        self.jobs.wake()
        return job

    # --- helpers --------------------------------------------------------------
    async def _free_slug(self, session: AsyncSession, base: str) -> str:
        taken = set(await session.scalars(
            select(Application.slug).where(Application.slug.like(f"{base}%"))
        ))  # fmt: skip
        if base not in taken:
            return base
        return next(f"{base}-{n}" for n in range(2, 10_000) if f"{base}-{n}" not in taken)
