"""Static sites: an nginx app marked ``static-site``, created with a first page.

A site is only ever an app this service created (``application.kind``): an nginx deployed
by hand from the catalog is not a site. Deploy, start and stop are the apps' own; the
site's files are written by its jobs, in the app's lane.
"""

import html
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from hivora.apps.core import DeployRequest, latest_revision
from hivora.apps.lifecycle import Deployer, Lifecycle
from hivora.apps.models import Application, DesiredState, Service
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.core.fs import confined, ensure_dir
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.state import AppStatus, StateStore

SITE_KIND = "static-site"
TEMPLATE = "nginx"
HTML_TARGET = "/usr/share/nginx/html"  # the nginx template's "html" volume

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
</head>
<body>
<h1>{title}</h1>
<p>Site prêt. / Site ready.</p>
</body>
</html>
"""


class SiteNotFoundError(NotFoundError):
    code = "site_not_found"


@dataclass(frozen=True, slots=True)
class Site:
    id: int
    slug: str
    name: str
    port: int | None
    zone_id: int | None
    enabled: bool
    deployed: bool  # its first deploy has run: it can be enabled or disabled
    status: AppStatus


class SiteService:
    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], deployer: Deployer,
        lifecycle: Lifecycle, jobs: JobQueue, settings: Settings, state: StateStore,
        bus: EventBus,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.deployer = deployer
        self.lifecycle = lifecycle
        self.jobs = jobs
        self.settings = settings
        self.state = state
        self.bus = bus

    def register(self) -> None:
        self.jobs.register(JobKind.SITE_CONTENT, self.initial_content)

    async def list(self) -> list[Site]:
        async with self.sessions() as session:
            apps = await session.scalars(
                select(Application).where(Application.kind == SITE_KIND).order_by(Application.name)
            )
            return [await self._site(session, app) for app in apps]

    async def create(self, name: str, port: int, zone: str | None) -> tuple[Site, Job, Job]:
        """The deploy job, then the first page's job in the same lane."""
        req = DeployRequest(TEMPLATE, name, {"web_port": port}, zone=zone, kind=SITE_KIND)
        app, deploy = await self.deployer.deploy(req)
        # ponytail: a second transaction; a crash in between leaves a site without its
        # first page (nginx answers 403) until its content is replaced (lot S2).
        async with self.sessions() as session, session.begin():
            content = self.jobs.add(session, JobKind.SITE_CONTENT, app_id=app.id,
                                    app_slug=app.slug)  # fmt: skip
        self.jobs.wake()
        async with self.sessions() as session:
            site = await self._site(session, await session.get_one(Application, app.id))
        return site, deploy, content

    async def set_enabled(self, app_id: int, enabled: bool) -> Job:
        """Start or stop; refused (409) until the first deploy has run."""
        async with self.sessions() as session:
            app = await self._get(session, app_id)
        job = await (self.lifecycle.start if enabled else self.lifecycle.stop)(app_id)
        topic = "site.enabled" if enabled else "site.disabled"
        self.bus.publish(topic, app=app.slug, job=job.id)
        return job

    async def initial_content(self, ctx: JobContext) -> None:
        """Write index.html once: an existing page is never replaced."""
        async with self.sessions() as session:
            app = await self._get(session, ctx.app_id or 0)
            if app.current_revision_id is None:
                raise ConflictError("site not deployed", slug=app.slug)
            html_dir = await self._html_dir(session, app.id)
        root = self.settings.volumes_root
        ensure_dir(html_dir, root, uid=self.settings.puid, gid=self.settings.pgid)
        index = confined(html_dir / "index.html", root)
        try:
            with index.open("x", encoding="utf-8") as f:  # "x": never overwrites
                f.write(PAGE.format(title=html.escape(app.name)))
        except FileExistsError:
            await ctx.log("index.html already there: kept")
            return
        index.chmod(0o644)
        if os.geteuid() == 0:
            os.chown(index, self.settings.puid, self.settings.pgid)
        await ctx.log("index.html written")

    async def _get(self, session: AsyncSession, app_id: int) -> Application:
        app = await session.get(Application, app_id)
        if app is None or app.kind != SITE_KIND:
            raise SiteNotFoundError(str(app_id))
        return app

    async def _html_dir(self, session: AsyncSession, app_id: int) -> Path:
        service = await session.scalar(
            select(Service).where(Service.app_id == app_id).options(selectinload(Service.volumes))
        )
        for volume in service.volumes if service else []:
            if volume.target == HTML_TARGET:
                return Path(volume.source)
        raise ConflictError("site has no html volume", app=app_id)

    async def _site(self, session: AsyncSession, app: Application) -> Site:
        revision = await latest_revision(session, app.id)
        port = revision.inputs.get("web_port") if revision else None
        return Site(
            id=app.id, slug=app.slug, name=app.name,
            port=int(port) if port is not None else None, zone_id=app.zone_id,
            enabled=app.desired_state is DesiredState.RUNNING,
            deployed=app.current_revision_id is not None,
            status=self.state.app(app.slug).status,
        )  # fmt: skip
