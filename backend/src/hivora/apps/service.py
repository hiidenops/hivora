"""Application commands. Every mutation is recorded as intent, then run as a job."""

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from hivora.jobs import Job, JobKind, JobQueue
from hivora.state import StateStore
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
from hivora.templates.models import TemplateVersion
from hivora.zones import Zone, get_zone


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
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.catalog = catalog
        self.runner = runner
        self.state = state
        self.jobs = jobs
        self.box = box
        self.bus = bus
        self.clock = clock or SystemClock()

    @property
    def host(self) -> HostInfo:
        s = self.settings
        return HostInfo(
            public_ip=s.host_public_ip,
            lan_ip=s.host_lan_ip,
            vpn_ip=s.host_vpn_ip,
            timezone=s.timezone,
            puid=s.puid,
            pgid=s.pgid,
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
        app_ctx = AppContext(
            slug=slug, name=name, revision=revision, zone=zone.slug if zone else None
        )
        host = self.host
        defaults_ctx = build_context(app_ctx, host, FormValues(), list(entry.template.services))
        form = validate_inputs(entry.template, inputs, defaults_ctx)
        compiled = compile_template(entry.template, app_ctx, host, form, self.settings.volumes_root)
        used = await used_ports(session, self.state, exclude_app=slug)
        conflicts = find_conflicts((p for s in compiled.services for p in s.ports), used)
        return DeployPlan(slug, name, entry, zone, compiled, form, conflicts)

    # --- settings (new revision) --------------------------------------------
    async def current_settings(self, session: AsyncSession, app_id: int) -> AppSettings:
        app = await self.get(session, app_id)
        entry = await self._entry_of(session, app)
        revision = await self._latest_revision(session, app.id)
        secrets = await self.decrypt_secrets(session, app.id)
        return AppSettings(app, entry, dict(revision.inputs) if revision else {}, sorted(secrets))

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
        return UpdatePlan(plan, number, diff)

    async def update(self, app_id: int, inputs: dict[str, Any]) -> Job:
        async with self.sessions() as session, session.begin():
            upd = await self.plan_update(session, app_id, inputs)
            plan = upd.plan
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
                params={"revision_id": revision.id},
            )
        self.jobs.wake()
        self.bus.publish("app.updated", app=app.slug, revision=upd.number, job=job.id)
        return job

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
                            read_only=v.read_only, backup=v.backup)
                for v in plan.volumes
            ],
        ))  # fmt: skip
    return services
