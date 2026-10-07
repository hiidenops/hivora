"""Applies a host's nginx configuration: the site_config job.

From the sites in the database, ``sites.nginx`` gives the exact set of Hivora's files in
the "conf" volume. The job writes the differences, has nginx check the whole
configuration (``nginx -t``), and only then reloads it. If nginx refuses, every file is
put back as it was: the configuration nginx runs never changed (nginx only reads its
files on a check, a reload or a start). The sites' intent stays in the database; the
failed job shows the gap.

Only fixed commands run in the container, through the gateway, never a shell; no
database transaction is open meanwhile.
"""

import asyncio
import logging
import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import LABEL_COMPOSE_SERVICE
from hivora.apps.models import Application
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, HivoraError
from hivora.core.events import EventBus
from hivora.core.fs import confined, remove_tree
from hivora.docker_gateway import ContainerInfo, ContainerState, DockerGateway
from hivora.jobs import Job, JobContext, JobKind, JobQueue, JobStatus
from hivora.sites import core
from hivora.sites.nginx import MANAGED, NginxSite, desired_files
from hivora.state import StateStore

logger = logging.getLogger(__name__)

CHECK = ["nginx", "-t"]
RELOAD = ["nginx", "-s", "reload"]
_OUTPUT = 2000  # characters of nginx's output kept in a job error


class NginxConfigRejectedError(ConflictError):
    code = "nginx_config_rejected"


Files = dict[str, str | None]  # name -> content (None: there, but not a regular file)


def read_managed(conf: Path) -> Files:
    """Hivora's files in the conf folder (named after MANAGED); others are not ours."""
    files: Files = {}
    for entry in sorted(conf.iterdir()):
        if MANAGED.match(entry.name):
            regular = entry.is_file() and not entry.is_symlink()
            files[entry.name] = entry.read_text() if regular else None
    return files


def write_files(conf: Path, work: Path, want: dict[str, str], have: Files, *, uid: int,
                gid: int) -> None:  # fmt: skip
    """Make the conf folder hold ``want``: each file through ``work`` (outside the mount,
    same filesystem) then one rename; files no longer wanted removed. Others untouched."""
    work.mkdir()
    try:
        for name, content in want.items():
            if have.get(name) != content:
                tmp = work / name
                tmp.write_text(content)
                tmp.chmod(0o644)
                if os.geteuid() == 0:
                    os.chown(tmp, uid, gid)
                os.replace(tmp, conf / name)
        for name in have.keys() - want.keys():
            (conf / name).unlink()
    finally:
        for leftover in work.iterdir():
            leftover.unlink()
        work.rmdir()


class SiteConfig:
    start_wait = 5.0  # seconds a job after a start waits for the container to be seen

    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], jobs: JobQueue,
        gateway: DockerGateway, state: StateStore, settings: Settings, bus: EventBus,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.jobs = jobs
        self.gateway = gateway
        self.state = state
        self.settings = settings
        self.bus = bus
        self._task: asyncio.Task[None] | None = None

    def register(self) -> None:
        self.jobs.register(JobKind.SITE_CONFIG, self.apply)

    async def start(self) -> None:
        sub = self.bus.subscribe("job.finished")
        self._task = asyncio.create_task(self._follow_starts(sub), name="site-config-starts")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _follow_starts(self, sub: Any) -> None:
        """A host started (or restarted): its configuration applied again, so nginx
        serves the sites as recorded even if its "conf" volume was lost or changed."""
        async with sub:
            async for event in sub:
                try:
                    await self._after_start(int(event.payload["id"]))
                except HivoraError:
                    pass  # not a host, or an nginx still on template 1.0.0
                except Exception:
                    logger.exception("site configuration not reapplied", extra=event.payload)

    async def _after_start(self, job_id: int) -> None:
        async with self.sessions() as session:
            job = await session.get(Job, job_id)
            if (job is None or job.app_id is None or job.status is not JobStatus.SUCCEEDED
                    or job.kind not in (JobKind.START, JobKind.RESTART)):  # fmt: skip
                return
            app_id = job.app_id
        await self.request(app_id, after_start=True)

    async def request(self, app_id: int, *, after_start: bool = False) -> Job:
        """Queue the job; refused (409) for an nginx still on the 1.0.0 template.
        ``after_start``: the host was just started, its container may not be seen yet."""
        async with self.sessions() as session, session.begin():
            app = await core.get_site(session, app_id)
            await core.conf_dir(session, app.id)
            params = {"after_start": True} if after_start else {}
            job = self.jobs.add(session, JobKind.SITE_CONFIG, app_id=app.id, app_slug=app.slug,
                                params=params)  # fmt: skip
        self.jobs.wake()
        return job

    def _container(self, slug: str) -> ContainerInfo | None:
        running = [c for c in self.state.app(slug).containers
                   if c.state is ContainerState.RUNNING
                   and c.labels.get(LABEL_COMPOSE_SERVICE) == core.SERVICE]  # fmt: skip
        return running[0] if running else None

    async def _wait_container(self, slug: str) -> ContainerInfo | None:
        """Just started: the state may not show the container yet (Docker's events)."""
        for _ in range(round(self.start_wait / 0.2)):
            if (container := self._container(slug)) is not None:
                return container
            await asyncio.sleep(0.2)
        return self._container(slug)

    async def _exec(self, ctx: JobContext, container: ContainerInfo, cmd: list[str]) -> tuple[
        int, str
    ]:  # fmt: skip
        code, out = await self.gateway.exec_run(container.id, cmd)
        await ctx.log(f"{' '.join(cmd)}: exit {code}\n{out.strip()[-_OUTPUT:]}".rstrip())
        return code, out

    async def apply(self, ctx: JobContext) -> None:
        """The site_config job."""
        async with self.sessions() as session:  # closed before any file or exec
            app = await core.get_site(session, ctx.app_id or 0)
            conf_path = await core.conf_dir(session, app.id)
            sites = await core.sites_of(session, app.id)
            folders = ctx.params.get("remove_folders") or []
            sites_path = await core.sites_dir(session, app.id) if folders else None
        try:
            await self._apply(ctx, app, conf_path, sites)
        finally:
            # A removed site's files, asked with remove_data: gone even if nginx refused
            # the configuration (the site's row and port are gone already).
            await self._remove_folders(ctx, sites_path, folders)

    async def _apply(self, ctx: JobContext, app: Application, conf_path: Path,
                     sites: list[NginxSite]) -> None:  # fmt: skip
        want = desired_files(sites)  # refuses any value that is not whitelisted
        root, s = self.settings.volumes_root, self.settings
        conf = confined(conf_path, root)
        work = confined(conf.parent / f".hivora-conf-{secrets.token_hex(8)}", root)
        await asyncio.to_thread(core.sweep, conf.parent, work)
        have = await asyncio.to_thread(read_managed, conf)
        if have == want:
            await ctx.log("configuration already up to date")
            return
        changed = sorted(n for n, c in want.items() if have.get(n) != c)
        removed = sorted(have.keys() - want.keys())

        async def rollback() -> None:
            # Back to the files as read: the ones written go, the ones there come back.
            # A non-regular file (None) is not recreated: regenerating it is the fix.
            before = {n: c for n, c in have.items() if c is not None}
            now = await asyncio.to_thread(read_managed, conf)
            await asyncio.to_thread(write_files, conf, work, before, now,
                                    uid=s.puid, gid=s.pgid)  # fmt: skip
            await ctx.log("files put back as they were")

        try:
            await asyncio.to_thread(write_files, conf, work, want, have, uid=s.puid, gid=s.pgid)
        except BaseException:
            await rollback()
            raise
        await ctx.log(f"written: {', '.join(changed) or '-'}; removed: {', '.join(removed) or '-'}")

        container = self._container(app.slug)
        if container is None and ctx.params.get("after_start"):
            container = await self._wait_container(app.slug)
        if container is None:
            await ctx.log("nginx is not running: it reads these files when it starts")
        else:
            # Reload only a configuration nginx has checked; on any refusal, the files
            # go back, and nginx checks (and reloads) the previous ones again.
            code, out = await self._exec(ctx, container, CHECK)
            if code != 0:
                await rollback()
                await self._exec(ctx, container, CHECK)
                raise NginxConfigRejectedError(
                    f"nginx refused the configuration: {out.strip()[-_OUTPUT:]}", app=app.slug
                )
            code, out = await self._exec(ctx, container, RELOAD)
            if code != 0:
                await rollback()
                await self._exec(ctx, container, CHECK)
                await self._exec(ctx, container, RELOAD)
                raise NginxConfigRejectedError(
                    f"nginx could not reload: {out.strip()[-_OUTPUT:]}", app=app.slug
                )
        self.bus.publish("site.config_applied", app=app.slug, files=changed, removed=removed)

    async def _remove_folders(self, ctx: JobContext, sites: Path | None, roots: list[str]) -> None:
        """A removed site's files, asked with remove_data, after nginx's files no longer
        name it. Each one confined to the sites volume."""
        for root in roots:
            if sites is not None and await asyncio.to_thread(remove_tree, sites / root, sites):
                await ctx.log(f"removed the files of {root}")
