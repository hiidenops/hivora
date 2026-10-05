"""Static sites: an nginx app marked ``static-site``, created with a first page.

A site is only ever an app this service created (``application.kind``): an nginx deployed
by hand from the catalog is not a site. Deploy, start and stop are the apps' own; the
site's files are written by its jobs, in the app's lane.
"""

import asyncio
import html
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import DeployRequest, latest_revision
from hivora.apps.lifecycle import Deployer, Lifecycle
from hivora.apps.models import Application, DesiredState
from hivora.core import archive, fs
from hivora.core.config import Settings
from hivora.core.events import EventBus
from hivora.core.fs import confined, ensure_dir
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.sites import core
from hivora.sites.core import SITE_KIND
from hivora.sites.models import Site as SiteRow
from hivora.state import AppStatus, StateStore

TEMPLATE = "nginx"
MAX_UPLOAD = 200 * 1024**2  # a zip, as sent

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
    max_upload = MAX_UPLOAD
    limits = archive.DEFAULT_LIMITS  # 10 000 files, 1 GiB once extracted

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
        self.jobs.register(JobKind.SITE_CONTENT, self.content)

    async def list(self) -> list[Site]:
        async with self.sessions() as session:
            apps = await session.scalars(
                select(Application).where(Application.kind == SITE_KIND).order_by(Application.name)
            )
            return [await self._site(session, app) for app in apps]

    async def create(self, name: str, port: int, zone: str | None) -> tuple[Site, Job, Job]:
        """The deploy job, then the first page's job in the same lane. The new host's main
        site (its html volume, on its web port) is recorded with that second job."""
        req = DeployRequest(TEMPLATE, name, {"web_port": port}, zone=zone, kind=SITE_KIND)
        app, deploy = await self.deployer.deploy(req)
        # ponytail: a second transaction; a crash in between leaves a site without its
        # first page (nginx answers 403) until its content is replaced (lot S2), and
        # without its main site row.
        async with self.sessions() as session, session.begin():
            main = SiteRow(app_id=app.id, slug="main", name=app.name, root="", port=None,
                           server_name=None, enabled=True, created_at=app.created_at)  # fmt: skip
            session.add(main)
            content = self.jobs.add(session, JobKind.SITE_CONTENT, app_id=app.id,
                                    app_slug=app.slug)  # fmt: skip
        self.jobs.wake()
        async with self.sessions() as session:
            site = await self._site(session, await session.get_one(Application, app.id))
        return site, deploy, content

    async def set_enabled(self, app_id: int, enabled: bool) -> Job:
        """Start or stop; refused (409) until the first deploy has run."""
        async with self.sessions() as session:
            app = await core.get_site(session, app_id)
        job = await (self.lifecycle.start if enabled else self.lifecycle.stop)(app_id)
        topic = "site.enabled" if enabled else "site.disabled"
        self.bus.publish(topic, app=app.slug, job=job.id)
        return job

    async def replace_content(self, app_id: int, filename: str, body: AsyncIterator[bytes]) -> Job:
        """Receive a zip next to the site, check it, then queue its replacement.

        A bad archive is refused here (422), before anything is queued; the job checks it
        again before writing anything.
        """
        async with self.sessions() as session:
            app = await core.get_site(session, app_id)
            html_dir = await core.html_dir(session, app.id)
        root, s = self.settings.volumes_root, self.settings
        await asyncio.to_thread(ensure_dir, html_dir.parent, root, uid=s.puid, gid=s.pgid)
        upload = confined(html_dir.parent / f".hivora-upload-{secrets.token_hex(8)}.zip", root)
        await fs.receive_upload(body, upload, limit=self.max_upload)
        try:
            await asyncio.to_thread(self._inspect, upload)
            params = {"upload": str(upload), "filename": filename[:100]}
            async with self.sessions() as session, session.begin():
                job = self.jobs.add(session, JobKind.SITE_CONTENT, app_id=app.id,
                                    app_slug=app.slug, params=params)  # fmt: skip
        except BaseException:
            upload.unlink(missing_ok=True)
            raise
        self.jobs.wake()
        return job

    async def content(self, ctx: JobContext) -> None:
        """The site_content job: a zip's content if one was sent, else the first page."""
        if "upload" in ctx.params:
            await self._replace(ctx)
        else:
            await self._initial(ctx)

    def _inspect(self, upload: Path) -> archive.Plan:
        with archive.open_zip(upload) as zf:
            return archive.inspect(zf, self.limits)

    async def _replace(self, ctx: JobContext) -> None:
        root, s = self.settings.volumes_root, self.settings
        upload = confined(Path(ctx.params["upload"]), root)
        staging = upload.with_name(f".hivora-staging-{secrets.token_hex(8)}")
        loop = asyncio.get_running_loop()

        def progress(pct: int) -> None:
            asyncio.run_coroutine_threadsafe(ctx.progress(pct, "Extracting the site"), loop)

        def work(html_dir: Path) -> tuple[archive.Plan, int]:
            core.sweep(html_dir.parent, keep=upload)
            with archive.open_zip(upload) as zf:
                plan = archive.inspect(zf, self.limits)
                written = archive.extract(zf, plan, staging, uid=s.puid, gid=s.pgid,
                                          limits=self.limits, progress=progress)  # fmt: skip
            fs.replace_contents(html_dir, staging, root)
            return plan, written

        try:
            app, html_dir = await core.deployed_html(self.sessions, ctx.app_id or 0)
            await ctx.log(f"extracting {ctx.params.get('filename') or upload.name}")
            plan, written = await asyncio.to_thread(work, html_dir)
        finally:
            upload.unlink(missing_ok=True)
            fs.remove_tree(staging, root)  # left as it was after a rollback
        files = plan.files()
        if plan.prefix:
            await ctx.log(f"top folder {plan.prefix} removed")
        if "index.html" not in files:
            await ctx.log("warning: no index.html at the root: nginx will answer 403")
        await ctx.log(f"content replaced: {len(files)} files, {written} bytes")
        self.bus.publish("site.content_replaced", app=app.slug, files=len(files),
                         bytes=written, filename=ctx.params.get("filename", ""))  # fmt: skip

    async def _initial(self, ctx: JobContext) -> None:
        """Write index.html once: an existing page is never replaced."""
        app, html_dir = await core.deployed_html(self.sessions, ctx.app_id or 0)
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
