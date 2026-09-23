"""Job handlers: the only place where app intents are applied to Docker."""

from pathlib import Path

from sqlalchemy import update

from hivora.apps.files import ensure_dir, remove_tree
from hivora.apps.models import Application, AppRevision, RevisionStatus
from hivora.apps.service import AppService
from hivora.compose_runner import ComposeError, ProgressEvent, ProgressStatus
from hivora.jobs import JobContext, JobKind
from hivora.templates.expressions import secret_env_name


class _PullProgress:
    """Maps compose pull events to a job percentage within [start, end]."""

    def __init__(self, ctx: JobContext, start: int, end: int) -> None:
        self.ctx, self.start, self.end = ctx, start, end
        self.layers: dict[str, int] = {}

    async def __call__(self, event: ProgressEvent) -> None:
        if event.parent is None:  # image-level or error events
            await self.ctx.log(f"{event.resource} {event.text} {event.details or ''}".strip())
            return
        self.layers[event.resource] = (
            100 if event.status is ProgressStatus.DONE else (event.percent or 0)
        )
        done = sum(self.layers.values()) / len(self.layers)
        await self.ctx.progress(self.start + round((self.end - self.start) * done / 100))


class AppJobHandlers:
    def __init__(self, service: AppService) -> None:
        self.s = service

    def register(self) -> None:
        q = self.s.jobs
        q.register(JobKind.DEPLOY, self.deploy)
        q.register(JobKind.START, self.start)
        q.register(JobKind.STOP, self.stop)
        q.register(JobKind.RESTART, self.restart)
        q.register(JobKind.REMOVE, self.remove)

    async def _log_event(self, ctx: JobContext, event: ProgressEvent) -> None:
        await ctx.log(f"{event.resource} {event.text} {event.details or ''}".strip())

    async def deploy(self, ctx: JobContext) -> None:
        s = self.s
        async with s.sessions() as session:
            app = await s.get(session, _app_id(ctx))
            revision = await session.get_one(AppRevision, ctx.params["revision_id"])
            secrets = await s.decrypt_secrets(session, app.id)
            sources = [v.source for svc in app.services for v in svc.volumes]
        ctx.add_secrets(secrets.values())
        env = {secret_env_name(k): v for k, v in secrets.items()}
        try:
            await ctx.progress(2, "Preparing directories and files")
            for source in sources:
                if ensure_dir(
                    Path(source), s.settings.volumes_root, uid=s.settings.puid, gid=s.settings.pgid
                ):
                    await ctx.log(f"created {source}")
            s.runner.write(app.slug, revision.compose_yaml, env)
            await s.runner.config(app.slug, redact=secrets.values())
            async with s.runner.lock(app.slug):
                await ctx.progress(5, "Pulling images")
                await s.runner.pull(
                    app.slug, on_progress=_PullProgress(ctx, 5, 80), redact=secrets.values()
                )
                await ctx.progress(80, "Starting containers")
                await self._up(ctx, app.slug, list(secrets.values()))
        except Exception:
            await self._set_revision(revision.id, RevisionStatus.FAILED)
            raise
        async with s.sessions() as session, session.begin():
            await session.execute(
                update(AppRevision)
                .where(AppRevision.app_id == app.id, AppRevision.status == RevisionStatus.APPLIED)
                .values(status=RevisionStatus.SUPERSEDED)
            )
            rev = await session.get_one(AppRevision, revision.id)
            rev.status, rev.applied_at = RevisionStatus.APPLIED, s.clock.now()
            (await session.get_one(Application, app.id)).current_revision_id = rev.id
        s.bus.publish("app.deployed", app=app.slug, revision=revision.number)

    async def start(self, ctx: JobContext) -> None:
        # `up` rather than `start`: recreates containers removed behind our back.
        slug, secrets = await self._slug_and_secrets(ctx)
        async with self.s.runner.lock(slug):
            await self._up(ctx, slug, secrets)

    async def stop(self, ctx: JobContext) -> None:
        slug, _ = await self._slug_and_secrets(ctx)
        async with self.s.runner.lock(slug):
            await self.s.runner.stop(slug, on_progress=lambda e: self._log_event(ctx, e))

    async def restart(self, ctx: JobContext) -> None:
        slug, _ = await self._slug_and_secrets(ctx)
        async with self.s.runner.lock(slug):
            await self.s.runner.restart(slug, on_progress=lambda e: self._log_event(ctx, e))

    async def remove(self, ctx: JobContext) -> None:
        s, remove_data = self.s, bool(ctx.params.get("remove_data"))
        slug, _ = await self._slug_and_secrets(ctx)
        async with s.runner.lock(slug):
            if s.runner.compose_path(slug).exists():
                await ctx.progress(10, "Removing containers and networks")
                await s.runner.down(
                    slug, remove_volumes=remove_data, on_progress=lambda e: self._log_event(ctx, e)
                )
            remove_tree(s.runner.project_dir(slug), s.runner.apps_dir)
            await ctx.log(f"removed {s.runner.project_dir(slug)}")
            if remove_data and remove_tree(s.volumes_dir(slug), s.settings.volumes_root):
                await ctx.log(f"removed {s.volumes_dir(slug)}")
        async with s.sessions() as session, session.begin():
            await session.delete(await s.get(session, _app_id(ctx)))
        s.bus.publish("app.removed", app=slug, data_removed=remove_data)

    async def _up(self, ctx: JobContext, slug: str, secrets: list[str]) -> None:
        """`compose up --wait`; on failure, append the containers' own logs to the job."""
        try:
            await self.s.runner.up(
                slug, redact=secrets, on_progress=lambda e: self._log_event(ctx, e)
            )
        except ComposeError as exc:
            try:
                lines = await self.s.runner.logs(slug, tail=40, redact=secrets)
            except Exception:
                lines = []
            if lines:
                await ctx.log("--- container logs (last 40 lines) ---")
                for line in lines:
                    await ctx.log(line)
            raise ComposeError(
                f"{exc}; see the container logs at the end of the job log", slug=slug
            ) from exc

    async def _slug_and_secrets(self, ctx: JobContext) -> tuple[str, list[str]]:
        async with self.s.sessions() as session:
            app = await self.s.get(session, _app_id(ctx))
            secrets = list((await self.s.decrypt_secrets(session, app.id)).values())
        ctx.add_secrets(secrets)
        return app.slug, secrets

    async def _set_revision(self, revision_id: int, status: RevisionStatus) -> None:
        async with self.s.sessions() as session, session.begin():
            (await session.get_one(AppRevision, revision_id)).status = status


def _app_id(ctx: JobContext) -> int:
    if ctx.app_id is None:
        raise ValueError("job without app")
    return ctx.app_id
