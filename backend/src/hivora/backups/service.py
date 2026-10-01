"""Archive an app's backup volumes (tar.gz), on demand or on a schedule; restore them.

A backup job stops the app first when the schedule says so (consistent game
worlds and databases), archives every volume marked `backup` in the template,
then starts the app again. Restoring stops the app, replaces each volume's
content with the archived one (ownership kept) and starts it again. Both run in
the app's job lane, so they never overlap with a deploy or an update.
"""

import asyncio
import logging
import shutil
import tarfile
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.models import Application, DesiredState
from hivora.apps.service import AppService
from hivora.backups.models import Backup, BackupSchedule
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.core.schedule import local_zone, next_run
from hivora.jobs import Job, JobContext, JobKind

logger = logging.getLogger(__name__)


class BackupNotFoundError(NotFoundError):
    code = "backup_not_found"


class NothingToBackUpError(ConflictError):
    code = "nothing_to_back_up"


class InvalidBackupError(ValidationError):
    code = "invalid_backup"


def archive(volumes: dict[str, Path], dest: Path) -> int:
    """Write ``dest`` (tar.gz) with each volume under its name; returns its size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with tarfile.open(tmp, "w:gz", compresslevel=6) as tar:
        for name, path in sorted(volumes.items()):
            if path.is_dir():
                tar.add(path, arcname=name)
    tmp.replace(dest)
    return dest.stat().st_size


def extract(src: Path, base: Path, volumes: dict[str, Path]) -> list[str]:
    """Replace each archived volume's content (volumes live in ``base``).

    Members outside the app's backup volumes are refused.
    """
    with tarfile.open(src, "r:gz") as tar:
        members = tar.getmembers()
        tops = {m.name.split("/", 1)[0] for m in members}
        if unknown := tops - set(volumes):
            raise InvalidBackupError("the archive holds unknown volumes", volumes=sorted(unknown))
        for name in tops:
            path = volumes[name]
            path.mkdir(parents=True, exist_ok=True)
            for child in path.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        # "tar" filter: no absolute paths, no escaping links; owners kept (numeric).
        tar.extractall(base, numeric_owner=True, filter="tar")
    return sorted(tops)


class BackupService:
    def __init__(self, apps: AppService) -> None:
        self.apps = apps
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def root(self) -> Path:
        return self.apps.settings.data_dir / "backups"

    @property
    def tz(self) -> ZoneInfo:
        return local_zone(self.apps.settings.timezone)

    def register(self) -> None:
        self.apps.jobs.register(JobKind.BACKUP, self.run_backup)
        self.apps.jobs.register(JobKind.BACKUP_RESTORE, self.run_restore)

    async def volumes(self, app: Application) -> dict[str, Path]:
        """Backup volumes of the app: name (folder under /srv/hivora/<slug>/) -> path."""
        base = self.apps.volumes_dir(app.slug)
        out = {}
        for svc in app.services:
            for v in svc.volumes:
                path = Path(v.source)
                if v.backup and path.parent == base:
                    out[path.name] = path
        return out

    # --- requests (API) ---------------------------------------------------
    async def request(self, app_id: int, *, scheduled: bool = False) -> Job:
        s = self.apps
        async with s.sessions() as session, session.begin():
            app = await s.get(session, app_id)
            if not await self.volumes(app):
                raise NothingToBackUpError("this app declares no volume to back up",
                                           slug=app.slug)  # fmt: skip
            now = s.clock.now()
            path = self.root / app.slug / f"{app.slug}-{now:%Y%m%d-%H%M%S}.tar.gz"
            backup = Backup(app_id=app.id, created_at=now, scheduled=scheduled, path=str(path))
            session.add(backup)
            await session.flush()
            schedule = await session.get(BackupSchedule, app.id)
            job = s.jobs.add(session, JobKind.BACKUP, app_id=app.id, app_slug=app.slug,
                             params={"backup_id": backup.id,
                                     "stop": schedule.stop if schedule else True})  # fmt: skip
        s.jobs.wake()
        return job

    async def restore(self, app_id: int, backup_id: int) -> Job:
        s = self.apps
        async with s.sessions() as session, session.begin():
            app = await s.get(session, app_id)
            backup = await self.get(session, app_id, backup_id)
            if backup.status != "ok":
                raise InvalidBackupError("this backup did not complete", id=backup_id)
            job = s.jobs.add(session, JobKind.BACKUP_RESTORE, app_id=app.id, app_slug=app.slug,
                             params={"backup_id": backup.id})  # fmt: skip
        s.jobs.wake()
        return job

    async def listing(self, session: AsyncSession,
                      app_id: int) -> tuple[BackupSchedule | None, list[Backup]]:  # fmt: skip
        """The app's backup schedule (None: never set) and its backups, newest first."""
        schedule = await session.get(BackupSchedule, app_id)
        rows = await session.scalars(
            select(Backup).where(Backup.app_id == app_id).order_by(Backup.created_at.desc())
        )
        return schedule, list(rows)

    async def get(self, session: AsyncSession, app_id: int, backup_id: int) -> Backup:
        backup = await session.get(Backup, backup_id)
        if backup is None or backup.app_id != app_id:
            raise BackupNotFoundError("unknown backup", id=backup_id)
        return backup

    async def delete(self, app_id: int, backup_id: int) -> None:
        async with self.apps.sessions() as session, session.begin():
            backup = await self.get(session, app_id, backup_id)
            await asyncio.to_thread(Path(backup.path).unlink, missing_ok=True)
            await session.delete(backup)
        self.apps.bus.publish("backup.deleted", app_id=app_id, target=Path(backup.path).name)

    async def set_schedule(self, app_id: int, **values: object) -> BackupSchedule:
        async with self.apps.sessions() as session, session.begin():
            await self.apps.get(session, app_id)
            row = await session.get(BackupSchedule, app_id) or BackupSchedule(app_id=app_id)
            for key, value in values.items():
                setattr(row, key, value)
            row.next_run_at = next_run(row, self.apps.clock.now(), self.tz) if row.enabled else None
            session.add(row)
        self.apps.bus.publish("backup.schedule_changed", app_id=app_id, enabled=row.enabled)
        return row

    # --- jobs ---------------------------------------------------------------
    async def _app(self, ctx: JobContext) -> tuple[Application, Backup, dict[str, Path]]:
        async with self.apps.sessions() as session:
            app = await self.apps.get(session, int(ctx.app_id or 0))
            backup = await self.get(session, app.id, int(ctx.params["backup_id"]))
            return app, backup, await self.volumes(app)

    async def _stopped(self, ctx: JobContext, app: Application, stop: bool) -> bool:
        """Stop the app if asked and it should run; True when it must be started again."""
        running = stop and app.desired_state is DesiredState.RUNNING
        if running:
            await ctx.log("stopping the app for a consistent copy")
            await self.apps.runner.stop(app.slug)
        return running

    async def run_backup(self, ctx: JobContext) -> None:
        app, backup, volumes = await self._app(ctx)
        restart = False
        try:
            async with self.apps.runner.lock(app.slug):
                restart = await self._stopped(ctx, app, bool(ctx.params.get("stop", True)))
                await ctx.progress(20, "Archiving the volumes")
                await ctx.log(f"archiving {', '.join(sorted(volumes))}")
                size = await asyncio.to_thread(archive, volumes, Path(backup.path))
                if restart:
                    await ctx.log("starting the app again")
                    await self.apps.runner.up(app.slug, wait=False)
        except Exception:
            await self._set(backup.id, status="failed")
            raise
        await self._set(backup.id, status="ok", size=size)
        await ctx.log(f"backup written: {Path(backup.path).name} ({size} bytes)")
        self.apps.bus.publish("backup.created", app=app.slug, target=Path(backup.path).name,
                              scheduled=backup.scheduled)  # fmt: skip
        if backup.scheduled:
            await self._prune(app.id)

    async def run_restore(self, ctx: JobContext) -> None:
        app, backup, volumes = await self._app(ctx)
        async with self.apps.runner.lock(app.slug):
            restart = await self._stopped(ctx, app, True)
            await ctx.progress(20, "Restoring the volumes")
            base = self.apps.volumes_dir(app.slug)
            restored = await asyncio.to_thread(extract, Path(backup.path), base, volumes)
            await ctx.log(f"restored {', '.join(restored)} from {Path(backup.path).name}")
            if restart:
                await ctx.log("starting the app again")
                await self.apps.runner.up(app.slug, wait=False)
        self.apps.bus.publish("backup.restored", app=app.slug, target=Path(backup.path).name)

    async def _set(self, backup_id: int, **values: object) -> None:
        async with self.apps.sessions() as session, session.begin():
            row = await session.get(Backup, backup_id)
            for key, value in values.items():
                setattr(row, key, value)

    async def _prune(self, app_id: int) -> None:
        """Keep the newest ``keep`` scheduled backups (manual ones stay until deleted)."""
        async with self.apps.sessions() as session, session.begin():
            schedule = await session.get(BackupSchedule, app_id)
            keep = schedule.keep if schedule else 7
            rows = list(await session.scalars(
                select(Backup).where(Backup.app_id == app_id, Backup.scheduled.is_(True),
                                     Backup.status == "ok")
                .order_by(Backup.created_at.desc())
            ))  # fmt: skip
            for old in rows[keep:]:
                await asyncio.to_thread(Path(old.path).unlink, missing_ok=True)
                await session.delete(old)

    # --- scheduler ----------------------------------------------------------
    async def tick(self) -> None:
        """Queue the backups that are due, and plan their next run."""
        now = self.apps.clock.now()
        async with self.apps.sessions() as session, session.begin():
            due = list(await session.scalars(select(BackupSchedule).where(
                BackupSchedule.enabled.is_(True), BackupSchedule.next_run_at <= now
            )))  # fmt: skip
            for row in due:
                row.next_run_at = next_run(row, now, self.tz)
        for row in due:
            try:
                await self.request(row.app_id, scheduled=True)
            except Exception:
                logger.exception("scheduled backup not queued", extra={"app_id": row.app_id})

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.tick()
            except Exception:
                logger.exception("backup scheduler failed")

    async def _forget_removed(self) -> None:
        """An app removed with its data takes its archives along."""
        async with self.apps.bus.subscribe("app.removed") as sub:
            async for event in sub:
                slug = str(event.payload.get("app", ""))
                folder = self.root / slug
                if event.payload.get("data_removed") and slug and folder.parent == self.root:
                    await asyncio.to_thread(shutil.rmtree, folder, True)

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop(), name="backup-scheduler"),
            asyncio.create_task(self._forget_removed(), name="backup-forget"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
