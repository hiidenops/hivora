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
import os
import secrets
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import LABEL_COMPOSE_SERVICE
from hivora.core.config import Settings
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.core.fs import confined, remove_tree
from hivora.docker_gateway import ContainerInfo, ContainerState, DockerGateway
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.sites import core
from hivora.sites.nginx import MANAGED, desired_files
from hivora.state import StateStore

SERVICE = "server"  # the nginx template's main service
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

    def register(self) -> None:
        self.jobs.register(JobKind.SITE_CONFIG, self.apply)

    async def request(self, app_id: int) -> Job:
        """Queue the job; refused (409) for an nginx still on the 1.0.0 template."""
        async with self.sessions() as session, session.begin():
            app = await core.get_site(session, app_id)
            await core.conf_dir(session, app.id)
            job = self.jobs.add(session, JobKind.SITE_CONFIG, app_id=app.id, app_slug=app.slug)
        self.jobs.wake()
        return job

    def _container(self, slug: str) -> ContainerInfo | None:
        running = [c for c in self.state.app(slug).containers
                   if c.state is ContainerState.RUNNING
                   and c.labels.get(LABEL_COMPOSE_SERVICE) == SERVICE]  # fmt: skip
        return running[0] if running else None

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
        want = desired_files(sites)  # refuses any value that is not whitelisted
        root, s = self.settings.volumes_root, self.settings
        conf = confined(conf_path, root)
        work = confined(conf.parent / f".hivora-conf-{secrets.token_hex(8)}", root)
        await asyncio.to_thread(core.sweep, conf.parent, work)
        have = await asyncio.to_thread(read_managed, conf)
        if have == want:
            await ctx.log("configuration already up to date")
            await self._remove_folders(ctx, sites_path, folders)
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
        await self._remove_folders(ctx, sites_path, folders)

    async def _remove_folders(self, ctx: JobContext, sites: Path | None, roots: list[str]) -> None:
        """A removed site's files, asked with remove_data: only once nginx no longer serves
        it (after a configuration it accepted). Each one confined to the sites volume."""
        for root in roots:
            if sites is not None and await asyncio.to_thread(remove_tree, sites / root, sites):
                await ctx.log(f"removed the files of {root}")
