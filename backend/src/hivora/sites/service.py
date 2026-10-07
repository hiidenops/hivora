"""A site's content from a zip: received next to the site, checked, then put in place by
a site_content job, in the app's lane (one site of an nginx that hosts sites)."""

import asyncio
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core import archive, fs
from hivora.core.config import Settings
from hivora.core.events import EventBus
from hivora.core.fs import confined, ensure_dir
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.sites import core

MAX_UPLOAD = 200 * 1024**2  # a zip, as sent


class SiteService:
    max_upload = MAX_UPLOAD
    limits = archive.DEFAULT_LIMITS  # 10 000 files, 1 GiB once extracted

    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], jobs: JobQueue, settings: Settings,
        bus: EventBus,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.jobs = jobs
        self.settings = settings
        self.bus = bus

    def register(self) -> None:
        self.jobs.register(JobKind.SITE_CONTENT, self.content)

    async def replace_content(
        self, app_id: int, filename: str, body: AsyncIterator[bytes], site_id: int | None = None
    ) -> Job:
        """Receive a zip next to the site, check it, then queue its replacement.

        A bad archive is refused here (422), before anything is queued; the job checks it
        again before writing anything. ``site_id``: one of the app's sites (None: its main
        site, as before sites had rows).
        """
        async with self.sessions() as session:
            app = await core.get_site(session, app_id)
            _, work = await core.site_root(session, app.id, site_id)
        root, s = self.settings.volumes_root, self.settings
        await asyncio.to_thread(ensure_dir, work, root, uid=s.puid, gid=s.pgid)
        upload = confined(work / f".hivora-upload-{secrets.token_hex(8)}.zip", root)
        await fs.receive_upload(body, upload, limit=self.max_upload)
        try:
            await asyncio.to_thread(self._inspect, upload)
            params: dict[str, object] = {"upload": str(upload), "filename": filename[:100]}
            if site_id is not None:
                params["site_id"] = site_id
            async with self.sessions() as session, session.begin():
                job = self.jobs.add(session, JobKind.SITE_CONTENT, app_id=app.id,
                                    app_slug=app.slug, params=params)  # fmt: skip
        except BaseException:
            upload.unlink(missing_ok=True)
            raise
        self.jobs.wake()
        return job

    async def content(self, ctx: JobContext) -> None:
        """The site_content job: the zip sent. A job without one was queued for a first page
        by the older site creation (removed): it ends without writing anything."""
        if "upload" not in ctx.params:
            await ctx.log("no archive: nothing to do (first page no longer written)")
            return
        await self._replace(ctx)

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

        def work(folder: Path, app_dir: Path) -> tuple[archive.Plan, int]:
            core.sweep(app_dir, keep=upload)
            ensure_dir(folder, root, uid=s.puid, gid=s.pgid)  # an added site's first content
            with archive.open_zip(upload) as zf:
                plan = archive.inspect(zf, self.limits)
                written = archive.extract(zf, plan, staging, uid=s.puid, gid=s.pgid,
                                          limits=self.limits, progress=progress)  # fmt: skip
            fs.replace_contents(folder, staging, root)
            return plan, written

        site_id = ctx.params.get("site_id")  # absent: the main site (jobs queued before)
        try:
            app, folder, app_dir = await core.deployed_root(self.sessions, ctx.app_id or 0, site_id)
            await ctx.log(f"extracting {ctx.params.get('filename') or upload.name}")
            plan, written = await asyncio.to_thread(work, folder, app_dir)
        finally:
            upload.unlink(missing_ok=True)
            fs.remove_tree(staging, root)  # left as it was after a rollback
        files = plan.files()
        if plan.prefix:
            await ctx.log(f"top folder {plan.prefix} removed")
        if "index.html" not in files:
            await ctx.log("warning: no index.html at the root: nginx will answer 403")
        await ctx.log(f"content replaced: {len(files)} files, {written} bytes")
        extra = {"site_id": site_id} if site_id is not None else {}
        self.bus.publish("site.content_replaced", app=app.slug, files=len(files), bytes=written,
                         filename=ctx.params.get("filename", ""), **extra)  # fmt: skip
