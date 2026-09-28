"""Application commands. Every mutation is recorded as intent, then run as a job."""

import difflib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.files import tree_size
from hivora.apps.models import (
    Application,
    AppRevision,
    AppSecret,
    DesiredState,
    Exposure,
    Origin,
    PortBinding,
    RevisionStatus,
    Service,
    ServiceRole,
    VolumeKind,
    VolumeMount,
)
from hivora.apps.ports import PortConflict, find_conflicts, used_ports
from hivora.compose_runner import ComposeRunner
from hivora.core.clock import Clock, SystemClock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.core.events import EventBus
from hivora.crypto.cipher import Purpose, Sealed, SecretBox
from hivora.docker_gateway import ContainerInfo, ContainerState, DockerGateway
from hivora.images.registry import Registry
from hivora.jobs import Job, JobKind, JobQueue
from hivora.state import StateStore, app_key
from hivora.system.secrets import SecretSetting, SecretSettings
from hivora.templates import (
    AppContext,
    Catalog,
    CatalogEntry,
    CompiledApp,
    FormValues,
    HostInfo,
    build_context,
    compile_template,
    host_arch,
    validate_inputs,
)
from hivora.templates.catalog import CUSTOM_SOURCE, TemplateInvalidError
from hivora.templates.custom import CustomApp, CustomEnv, CustomPort
from hivora.templates.custom import manifest as custom_manifest
from hivora.templates.models import TemplateVersion
from hivora.zones import Zone, get_zone, zone_network

LABEL_COMPOSE_SERVICE = "com.docker.compose.service"


class AppNotFoundError(NotFoundError):
    code = "app_not_found"


class PortConflictError(ConflictError):
    code = "port_conflict"


class UnsupportedArchitectureError(ValidationError):
    code = "unsupported_architecture"


@dataclass(frozen=True, slots=True)
class DeployRequest:
    template: str
    name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    slug: str | None = None
    zone: str | None = None  # zone slug; None: "unclassified"


@dataclass(frozen=True, slots=True)
class DeployPlan:
    """Everything the user reviews before deploying (radical transparency)."""

    slug: str
    name: str
    entry: CatalogEntry
    zone: Zone | None
    compiled: CompiledApp
    form: FormValues
    conflicts: list[PortConflict]


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


class DataResetRequiredError(ConflictError):
    code = "data_reset_required"


@dataclass(frozen=True, slots=True)
class AppSettings:
    app: Application
    entry: CatalogEntry
    values: dict[str, Any]  # latest revision inputs (secrets excluded)
    secrets_set: list[str]  # secret keys that already have a value


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    slug: str
    containers: list[str]
    files: list[str]  # compose.yaml, .env: always removed
    data: list[str]  # bind-mounted data: removed only on explicit request


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:50].strip("-") or "app"


def vars_of_host(host: HostInfo) -> dict[str, Any]:
    return {f: getattr(host, f) for f in host.__slots__}  # slots dataclass: no __dict__


def secret_context(app_id: int, key: str) -> str:
    return f"app:{app_id}:{key}"


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
        self.registry = registry or Registry()
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

    @property
    def host(self) -> HostInfo:
        s = self.settings
        return HostInfo(
            public_ip=self.public_address() if self.public_address else s.host_public_ip,
            lan_ip=s.host_lan_ip,
            vpn_ip=s.host_vpn_ip,
            timezone=s.timezone,
            puid=s.puid,
            pgid=s.pgid,
            arch=host_arch(),
        )

    def volumes_dir(self, slug: str) -> Path:
        return self.settings.volumes_root / slug

    # --- queries ------------------------------------------------------------
    async def get(self, session: AsyncSession, app_id: int) -> Application:
        app = await session.get(Application, app_id)
        if app is None:
            raise AppNotFoundError(str(app_id))
        return app

    async def decrypt_secrets(self, session: AsyncSession, app_id: int) -> dict[str, str]:
        rows = await session.scalars(select(AppSecret).where(AppSecret.app_id == app_id))
        return {
            s.key: self.box.open(
                Purpose.APP_SECRET, Sealed(s.nonce, s.ciphertext), secret_context(app_id, s.key)
            )
            for s in rows
        }

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
        return await self._plan(session, entry, slug, name, zone, req.inputs, revision=1)

    async def _plan(
        self,
        session: AsyncSession,
        entry: CatalogEntry,
        slug: str,
        name: str,
        zone: Zone | None,
        inputs: dict[str, Any],
        *,
        revision: int,
    ) -> DeployPlan:
        inputs = await self._with_setting_fallbacks(entry, inputs)
        app_ctx = AppContext(
            slug=slug, name=name, revision=revision, zone=zone.slug if zone else None,
            zone_network=zone_network(zone),
            extra_networks=await self._vpn_networks(session, entry, inputs),
        )  # fmt: skip
        host = self.host
        defaults_ctx = build_context(app_ctx, host, FormValues(), list(entry.template.services))
        form = validate_inputs(entry.template, inputs, defaults_ctx)
        compiled = compile_template(entry.template, app_ctx, host, form, self.settings.volumes_root)
        used = await used_ports(session, self.state, exclude_app=slug)
        conflicts = find_conflicts((p for s in compiled.services for p in s.ports), used)
        return DeployPlan(slug, name, entry, zone, compiled, form, conflicts)

    async def _with_setting_fallbacks(
        self, entry: CatalogEntry, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Empty secrets declaring `from_setting` take the global setting's value."""
        if self.secret_settings is None:
            return inputs
        filled = dict(inputs)
        for f in entry.template.form.fields:
            if f.type == "secret" and f.from_setting and not filled.get(f.id):
                value = await self.secret_settings.get(SecretSetting(f.from_setting))
                if value:
                    filled[f.id] = value
        return filled

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
            entry = await self._entry_of(session, app)
        except (ConflictError, NotFoundError):
            return {}
        latest = await self._latest_revision(session, app.id)
        if latest is None:
            return {}
        ctx = AppContext(slug=app.slug, name=app.name, revision=latest.number)
        form = FormValues(dict(latest.inputs))
        host = self.host
        access = compile_template(
            entry.template, ctx, host, form, self.settings.volumes_root
        ).access
        # Same addresses on the local network, when they differ (e.g. public IP vs LAN).
        lan_host = HostInfo(**{**vars_of_host(host), "public_ip": None})
        local = compile_template(
            entry.template, ctx, lan_host, form, self.settings.volumes_root
        ).access
        for key, value in local.items():
            if access.get(key) != value:
                access[f"{key}_lan"] = value
        return access

    # --- settings (new revision) --------------------------------------------
    async def current_settings(self, session: AsyncSession, app_id: int) -> AppSettings:
        app = await self.get(session, app_id)
        entry = await self._entry_of(session, app)
        revision = await self._latest_revision(session, app.id)
        secrets = await self.decrypt_secrets(session, app.id)
        known = {f.id for f in entry.template.form.fields}  # a newer template may drop fields
        values = {k: v for k, v in (revision.inputs if revision else {}).items() if k in known}
        return AppSettings(app, entry, values, sorted(secrets))

    async def plan_update(
        self, session: AsyncSession, app_id: int, inputs: dict[str, Any]
    ) -> UpdatePlan:
        """Preview a settings change: new compose, its diff, port conflicts.

        Secret fields left empty keep their current value.
        """
        app = await self.get(session, app_id)
        entry = await self._entry_of(session, app)
        current = await self.decrypt_secrets(session, app.id)
        kept = {k: v for k, v in current.items() if not inputs.get(k)}
        latest = await self._latest_revision(session, app.id)
        number = (latest.number if latest else 0) + 1
        zone = await session.get(Zone, app.zone_id) if app.zone_id else None
        plan = await self._plan(session, entry, app.slug, app.name, zone, {**inputs, **kept},
                                revision=number)  # fmt: skip
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
        if not reset_fields:
            return UpdatePlan(plan, number, diff)
        specs = entry.template.services
        reset_volumes = {
            str(v.source): next(x.reset_keep for x in specs[v.service].volumes if x.name == v.name)
            for svc in plan.compiled.services for v in svc.volumes if not v.read_only
        }  # fmt: skip
        size = sum(tree_size(Path(p)) for p in reset_volumes)
        return UpdatePlan(plan, number, diff, reset_fields, reset_volumes, size)

    async def update(self, app_id: int, inputs: dict[str, Any], *, reset_data: bool = False) -> Job:
        async with self.sessions() as session, session.begin():
            upd = await self.plan_update(session, app_id, inputs)
            plan = upd.plan
            if upd.reset_fields and not reset_data:
                raise DataResetRequiredError(
                    "this change erases the app data and must be confirmed",
                    fields=upd.reset_fields,
                )
            if plan.conflicts:
                raise PortConflictError(
                    "host ports already in use",
                    conflicts=[_conflict_dict(c) for c in plan.conflicts],
                )
            app = await self.get(session, app_id)
            version = await self._template_version(session, plan.entry)
            app.template_version_id = version.id
            await session.execute(delete(AppSecret).where(AppSecret.app_id == app.id))
            for key, value in plan.form.secrets.items():
                sealed = self.box.seal(Purpose.APP_SECRET, value, secret_context(app.id, key))
                session.add(
                    AppSecret(
                        app_id=app.id, key=key, ciphertext=sealed.ciphertext, nonce=sealed.nonce
                    )
                )
            # The declared services now describe the new revision. Delete the old
            # ones first (orphan cascade + flush): same names, unique per app.
            app.services.clear()
            await session.flush()
            app.services = _services_from(plan.compiled)
            revision = AppRevision(
                app_id=app.id, number=upd.number, inputs=plan.form.values,
                compose_yaml=plan.compiled.compose_yaml, diff_from_previous=upd.diff,
                created_at=self.clock.now(), status=RevisionStatus.PENDING,
            )  # fmt: skip
            session.add(revision)
            await session.flush()
            app.desired_state = DesiredState.RUNNING
            job = self.jobs.add(
                session,
                JobKind.UPDATE,
                app_id=app.id,
                app_slug=app.slug,
                params={"revision_id": revision.id}
                | ({"reset_volumes": upd.reset_volumes} if upd.reset_fields else {}),
            )
        self.jobs.wake()
        self.bus.publish("app.updated", app=app.slug, revision=upd.number, job=job.id)
        return job

    # --- free images (any registry image, through a generated template) -------
    async def custom_request(
        self, name: str, image: str, zone: str | None, ports: list[CustomPort],
        volumes: list[str], env: list[CustomEnv],
    ) -> DeployRequest:  # fmt: skip
        """Read the image from its registry, pin it, generate its template."""
        arch = host_arch()
        info = await self.registry.inspect(image, arch)
        if arch not in info.platforms:
            raise UnsupportedArchitectureError(
                f"{info.ref.name}:{info.ref.tag} has no {arch} build", arch=arch,
                platforms=info.platforms,
            )  # fmt: skip
        spec = CustomApp(slugify(name), name, info.ref.name, f"{info.ref.tag}@{info.digest}",
                         info.platforms, ports, volumes, env)  # fmt: skip
        try:
            text = custom_manifest(spec, version=f"1.0.{int(self.clock.now().timestamp())}")
            entry = self.catalog.add_custom(text)
        except (ValueError, TemplateInvalidError) as exc:
            raise ValidationError(str(exc)[:300]) from exc
        inputs: dict[str, Any] = {f"env_{i}": e.value for i, e in enumerate(env)}
        inputs |= {f"port_{i}": p.host for i, p in enumerate(ports)}
        return DeployRequest(entry.slug, name, inputs, zone=zone)

    async def load_custom_templates(self) -> None:
        """Templates generated for free images live in the database: register them."""
        async with self.sessions() as session:
            rows = await session.scalars(
                select(TemplateVersion.manifest).where(TemplateVersion.source == CUSTOM_SOURCE)
                .order_by(TemplateVersion.created_at)
            )  # fmt: skip
            for text in rows:
                try:
                    self.catalog.add_custom(text)
                except TemplateInvalidError:  # pragma: no cover - written by us
                    continue

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

    async def _vpn_networks(
        self, session: AsyncSession, entry: CatalogEntry, inputs: dict[str, Any]
    ) -> tuple[str, ...]:
        """A VPN reaching zones joins their networks (only "linked together" zones have one)."""
        vpn = entry.template.vpn
        if not vpn or not vpn.zones_field:
            return ()
        names = []
        for slug in (s for s in str(inputs.get(vpn.zones_field) or "").split(",") if s):
            name = zone_network(await get_zone(session, slug))
            if name is None:
                raise ValidationError("this zone does not link its apps: no network to reach",
                                      field=vpn.zones_field, zone=slug)  # fmt: skip
            names.append(name)
        return tuple(names)

    async def _entry_of(self, session: AsyncSession, app: Application) -> CatalogEntry:
        slug = await session.scalar(
            select(TemplateVersion.slug).where(TemplateVersion.id == app.template_version_id)
        )
        if slug is None:
            raise ConflictError("this app was not deployed from a template", slug=app.slug)
        return self.catalog.get(slug)

    @staticmethod
    async def _latest_revision(session: AsyncSession, app_id: int) -> AppRevision | None:
        latest: AppRevision | None = await session.scalar(
            select(AppRevision).where(AppRevision.app_id == app_id)
            .order_by(AppRevision.number.desc()).limit(1)
        )  # fmt: skip
        return latest

    async def deploy(self, req: DeployRequest) -> tuple[Application, Job]:
        async with self.sessions() as session, session.begin():
            plan = await self.plan_deploy(session, req)
            if plan.conflicts:
                raise PortConflictError(
                    "host ports already in use",
                    conflicts=[_conflict_dict(c) for c in plan.conflicts],
                )
            version = await self._template_version(session, plan.entry)
            app = Application(
                slug=plan.slug, name=plan.name, zone_id=plan.zone.id if plan.zone else None,
                origin=Origin.TEMPLATE, template_version_id=version.id,
                desired_state=DesiredState.RUNNING, icon=None,
                notes="", created_at=self.clock.now(), services=_services_from(plan.compiled),
            )  # fmt: skip
            session.add(app)
            await session.flush()
            for key, value in plan.form.secrets.items():
                sealed = self.box.seal(Purpose.APP_SECRET, value, secret_context(app.id, key))
                session.add(
                    AppSecret(
                        app_id=app.id, key=key, ciphertext=sealed.ciphertext, nonce=sealed.nonce
                    )
                )
            revision = AppRevision(
                app_id=app.id, number=1, inputs=plan.form.values,
                compose_yaml=plan.compiled.compose_yaml, created_at=self.clock.now(),
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
        project = self.runner.project_dir(app.slug)
        data = self.volumes_dir(app.slug)
        return RemovalPlan(
            slug=app.slug,
            containers=sorted(c.name for c in self.state.app(app.slug).containers),
            files=[str(p) for p in sorted(project.glob("*"))] if project.exists() else [],
            data=[str(data)] if data.exists() else [],
        )

    async def remove(self, app_id: int, *, remove_data: bool = False) -> Job:
        async with self.sessions() as session, session.begin():
            app = await self.get(session, app_id)
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
            if app.current_revision_id is None:
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

    async def _template_version(
        self, session: AsyncSession, entry: CatalogEntry
    ) -> TemplateVersion:
        meta = entry.template.metadata
        existing = await session.scalar(
            select(TemplateVersion).where(
                TemplateVersion.source == entry.source,
                TemplateVersion.slug == meta.slug,
                TemplateVersion.version == meta.version,
            )
        )
        if existing:
            if existing.checksum != entry.checksum:
                raise ConflictError(
                    "template changed without a version bump", slug=meta.slug, version=meta.version
                )
            return existing
        version = TemplateVersion(
            source=entry.source, slug=meta.slug, version=meta.version,
            api_version=entry.template.api_version, name=meta.name, category=meta.category,
            manifest=entry.manifest, checksum=entry.checksum, created_at=self.clock.now(),
        )  # fmt: skip
        session.add(version)
        await session.flush()
        return version


def _conflict_dict(conflict: PortConflict) -> dict[str, Any]:
    return {
        "port": conflict.port,
        "protocol": conflict.protocol,
        "used_by": conflict.used_by,
        "suggestion": conflict.suggestion,
    }


def _services_from(compiled: CompiledApp) -> list[Service]:
    services = []
    for plan in compiled.services:
        services.append(Service(
            name=plan.name, image=plan.image, role=ServiceRole(plan.role),
            restart_policy=plan.restart,
            ports=[
                PortBinding(host_ip=p.host_ip, host_port=p.host_port,
                            container_port=p.container_port, protocol=p.protocol,
                            purpose=p.purpose, exposure=Exposure(p.exposure))
                for p in plan.ports
            ],
            volumes=[
                VolumeMount(kind=VolumeKind.BIND, source=str(v.source), target=v.target,
                            read_only=v.read_only, backup=v.backup, owner=v.owner)
                for v in plan.volumes
            ],
        ))  # fmt: skip
    return services
