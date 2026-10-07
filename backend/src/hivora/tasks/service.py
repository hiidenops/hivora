"""Scheduled tasks: a simplified cron per app.

Each task has one action (restart, stop, start, backup, or a command run in a
container, as a shell command or through the game's console) and a schedule
(every day / week at a local time, or every N hours), checked every minute.
Lifecycle actions and backups go through the app's job lane like any other
action; commands run by exec (never on the host) with a time limit.
"""

import asyncio
import logging
import shlex
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.core import decrypt_secrets, get_app
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.core.redact import Redactor
from hivora.core.schedule import local_zone, next_run
from hivora.docker_gateway import ContainerState
from hivora.runtime import Runtime
from hivora.state import app_key
from hivora.tasks.models import ScheduledTask

logger = logging.getLogger(__name__)

ACTIONS = ("restart", "stop", "start", "backup", "command")
COMMAND_TIMEOUT_S = 120
OUTPUT_MAX = 4000
SERVICE_LABEL = "com.docker.compose.service"


class TaskNotFoundError(NotFoundError):
    code = "task_not_found"


class TaskFailedError(ConflictError):
    code = "task_failed"


class TaskTools:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def get(self, session: AsyncSession, app_id: int, task_id: int) -> ScheduledTask:
        task = await session.get(ScheduledTask, task_id)
        if task is None or task.app_id != app_id:
            raise TaskNotFoundError("unknown task", id=task_id)
        return task

    async def list(self, app_id: int) -> list[ScheduledTask]:
        async with self.rt.sessions() as session:
            await get_app(session, app_id)
            rows = await session.scalars(
                select(ScheduledTask).where(ScheduledTask.app_id == app_id)
                .order_by(ScheduledTask.id)
            )  # fmt: skip
            return list(rows)

    async def _check(self, session: AsyncSession, app_id: int, values: dict[str, Any]) -> None:
        if values.get("action") == "command":
            if not str(values.get("command") or "").strip():
                raise ValidationError("a command is required", field="command")
            if values.get("mode") == "console":
                _, entry, _ = await self.rt.apps.main_container(session, app_id)
                game = entry.template.game if entry else None
                if not (game and game.console):
                    raise ValidationError("this app has no game console", field="mode")

    async def save(self, app_id: int, values: dict[str, Any], task_id: int | None = None) -> int:
        async with self.rt.sessions() as session, session.begin():
            app = await get_app(session, app_id)
            await self._check(session, app_id, values)
            task = await self.get(session, app_id, task_id) if task_id else ScheduledTask(
                app_id=app_id, last_output="")  # fmt: skip
            for key, value in values.items():
                setattr(task, key, value)
            now = self.rt.clock.now()
            task.next_run_at = next_run(task, now, self._tz) if task.enabled else None
            session.add(task)
            await session.flush()
            tid = task.id
        self.rt.bus.publish("task.saved", app=app.slug, target=values.get("name"))
        return tid

    async def delete(self, app_id: int, task_id: int) -> None:
        async with self.rt.sessions() as session, session.begin():
            task = await self.get(session, app_id, task_id)
            await session.delete(task)
        self.rt.bus.publish("task.deleted", app_id=app_id, target=task.name)

    @property
    def _tz(self) -> Any:
        return local_zone(self.rt.settings.timezone)

    # --- running ----------------------------------------------------------------
    async def run(self, app_id: int, task_id: int) -> tuple[str, str]:
        """Run now; returns (status, output). Lifecycle and backups are queued jobs."""
        async with self.rt.sessions() as session:
            task = await self.get(session, app_id, task_id)
        try:
            status, output = await self._execute(task)
        except Exception as exc:  # recorded on the task, shown on the card
            status, output = "failed", str(exc)[:OUTPUT_MAX]
        async with self.rt.sessions() as session, session.begin():
            row = await self.get(session, app_id, task_id)
            row.last_run_at, row.last_status, row.last_output = (
                self.rt.clock.now(),
                status,
                output[-OUTPUT_MAX:],
            )
        self.rt.bus.publish("task.ran", app_id=app_id, target=task.name, status=status)
        return status, output

    async def _execute(self, task: ScheduledTask) -> tuple[str, str]:
        apps = self.rt.apps
        if task.action in ("restart", "stop", "start"):
            job = await getattr(apps.lifecycle, task.action)(task.app_id)
            return "queued", f"job #{job.id}"
        if task.action == "backup":
            job = await self.rt.backups.request(task.app_id, scheduled=True)
            return "queued", f"job #{job.id}"
        return await self._command(task)

    async def _command(self, task: ScheduledTask) -> tuple[str, str]:
        async with self.rt.sessions() as session:
            app, entry, main = await self.rt.apps.main_container(session, task.app_id)
            secrets = await decrypt_secrets(session, self.rt.box, app.id)
        container = main
        if task.service:
            running = (c for c in self.rt.state.store.containers()
                       if app_key(c) == app.slug and c.state is ContainerState.RUNNING)  # fmt: skip
            container = next((c for c in running if c.labels.get(SERVICE_LABEL) == task.service),
                             None)  # fmt: skip
        if container is None:
            raise TaskFailedError("the container is not running")
        game = entry.template.game if entry else None
        user = None
        if task.mode == "console":
            if not (game and game.console):
                raise TaskFailedError("this app has no game console")
            argv = [*game.console, *shlex.split(task.command)]
            s = self.rt.settings
            user = f"{s.puid}:{s.pgid}" if game.run_as == "app" else None
        else:
            argv = ["sh", "-c", task.command]
        async with asyncio.timeout(COMMAND_TIMEOUT_S):
            code, out = await self.rt.gateway.exec_run(container.id, argv, user)
        out = Redactor(secrets.values())(out)
        return ("ok" if code == 0 else "failed"), out if code == 0 else f"exit {code}\n{out}"

    # --- scheduler ----------------------------------------------------------------
    async def tick(self) -> None:
        now = self.rt.clock.now()
        async with self.rt.sessions() as session, session.begin():
            due = list(await session.scalars(select(ScheduledTask).where(
                ScheduledTask.enabled.is_(True), ScheduledTask.next_run_at <= now
            )))  # fmt: skip
            for task in due:
                task.next_run_at = next_run(task, now, self._tz)
            todo = [(t.app_id, t.id) for t in due]
        for app_id, task_id in todo:
            await self.run(app_id, task_id)


async def run_scheduler(rt: Runtime) -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await TaskTools(rt).tick()
        except Exception:
            logger.exception("task scheduler failed")
