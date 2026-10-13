"""Deployment and lifecycle of an app: deploy from a template, start / stop / restart,
removal. Each action records the intent and queues its job."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hivora.apps.links as links
from hivora.apps.core import (
    DeployRequest,
    PortConflictError,
    UnsupportedArchitectureError,
    conflict_dict,
    get_app,
    slugify,
    store_secrets,
)
from hivora.apps.models import Application, AppRevision, DesiredState, Origin, RevisionStatus
from hivora.apps.planner import AppPlanner, DeployPlan, services_from
from hivora.compose_runner import ComposeRunner
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox
from hivora.jobs import Job, JobKind, JobQueue
from hivora.state import StateStore
from hivora.templates import Catalog
from hivora.zones import get_zone


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    slug: str
    containers: list[str]
    files: list[str]  # compose.yaml, .env: always removed
    data: list[str]  # bind-mounted data: removed only on explicit request


class Deployer:
    """A new app from a catalog template: plan (reviewed first), then the deploy job."""

    def __init__(
        self, *, planner: AppPlanner, sessions: async_sessionmaker[AsyncSession],
        catalog: Catalog, jobs: JobQueue, box: SecretBox, bus: EventBus, clock: Clock,
    ) -> None:  # fmt: skip
        self.planner = planner
        self.sessions = sessions
        self.catalog = catalog
        self.jobs = jobs
        self.box = box
        self.bus = bus
        self.clock = clock

    async def plan_deploy(self, session: AsyncSession, req: DeployRequest) -> DeployPlan:
        entry = self.catalog.get(req.template)
        if not entry.supports(self.catalog.host_arch()):
            raise UnsupportedArchitectureError(entry.slug, arch=self.catalog.host_arch())
        name = req.name.strip() or entry.template.metadata.name
        slug = req.slug or await self._free_slug(session, slugify(name))
        if req.slug and await session.scalar(
            select(Application.id).where(Application.slug == slug)
        ):
            raise ConflictError("slug already used", slug=slug)
        zone = await get_zone(session, req.zone) if req.zone else None
        return await self.planner.plan(session, entry, slug, name, zone, req.inputs, revision=1)

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
                notes="", created_at=self.clock.now(),
                services=services_from(plan.compiled),
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

    async def _free_slug(self, session: AsyncSession, base: str) -> str:
        taken = set(await session.scalars(
            select(Application.slug).where(Application.slug.like(f"{base}%"))
        ))  # fmt: skip
        if base not in taken:
            return base
        return next(f"{base}-{n}" for n in range(2, 10_000) if f"{base}-{n}" not in taken)


class Lifecycle:
    """Start, stop, restart and removal of a deployed (or adopted) app."""

    def __init__(
        self, *, planner: AppPlanner, sessions: async_sessionmaker[AsyncSession],
        settings: Settings, runner: ComposeRunner, state: StateStore, jobs: JobQueue,
    ) -> None:  # fmt: skip
        self.planner = planner
        self.sessions = sessions
        self.settings = settings
        self.runner = runner
        self.state = state
        self.jobs = jobs

    async def start(self, app_id: int) -> Job:
        return await self._lifecycle(app_id, JobKind.START, DesiredState.RUNNING)

    async def stop(self, app_id: int) -> Job:
        return await self._lifecycle(app_id, JobKind.STOP, DesiredState.STOPPED)

    async def restart(self, app_id: int) -> Job:
        return await self._lifecycle(app_id, JobKind.RESTART, DesiredState.RUNNING)

    async def removal_plan(self, app_id: int) -> RemovalPlan:
        async with self.sessions() as session:
            app = await get_app(session, app_id)
        if app.origin is Origin.ADOPTED:  # forgotten only: its containers keep running
            return RemovalPlan(slug=app.slug, containers=[], files=[], data=[])
        project = self.runner.project_dir(app.slug)
        data = self.settings.volumes_root / app.slug
        return RemovalPlan(
            slug=app.slug,
            containers=sorted(c.name for c in self.state.app(app.slug).containers),
            files=[str(p) for p in sorted(project.glob("*"))] if project.exists() else [],
            data=[str(data)] if data.exists() else [],
        )

    async def remove(self, app_id: int, *, remove_data: bool = False) -> Job:
        async with self.sessions() as session, session.begin():
            app = await get_app(session, app_id)
            if vpns := await self.planner.vpns_reaching(session, app.slug):
                raise ConflictError("this app is behind a VPN: detach it from the VPN first",
                                    vpn=", ".join(vpns))  # fmt: skip
            # A tool linked to it would lose its network (it would not start any more).
            if tools := await links.linked_by(session, self.planner.catalog, app.slug):
                raise links.LinkedAppError("tools are linked to this app: unlink them first",
                                           tools=", ".join(tools))  # fmt: skip
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
            app = await get_app(session, app_id)
            if app.current_revision_id is None and app.origin is not Origin.ADOPTED:
                raise ConflictError("app has never been deployed", slug=app.slug)
            app.desired_state = desired
            job = self.jobs.add(session, kind, app_id=app.id, app_slug=app.slug)
        self.jobs.wake()
        return job
