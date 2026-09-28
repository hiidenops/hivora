"""Scheduled task routes, mounted under /api/v1/apps: /{app_id}/tasks/..."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.tasks.models import ScheduledTask
from hivora.tasks.service import TaskTools
from hivora.web.deps import Operator, RuntimeDep

router = APIRouter(tags=["tasks"])


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    action: Literal["restart", "stop", "start", "backup", "command"]
    mode: Literal["shell", "console"] = "shell"
    service: str | None = Field(default=None, max_length=63)  # command: None = main service
    command: str = Field(default="", max_length=2000)
    frequency: Literal["daily", "weekly", "hours"] = "daily"
    hour: int = Field(default=4, ge=0, le=23)  # local time (HIVORA_TIMEZONE)
    minute: int = Field(default=0, ge=0, le=59)
    weekday: int = Field(default=0, ge=0, le=6)  # weekly: 0 = Monday
    every_hours: int = Field(default=6, ge=1, le=168)


class TaskOut(TaskIn):
    id: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None  # ok, failed, queued (a job was started)
    last_output: str


class TasksOut(BaseModel):
    timezone: str  # schedules are in this local time
    services: list[str]  # where a shell command can run
    console: bool  # the app has a game console (command mode "console")
    tasks: list[TaskOut]


class RunOut(BaseModel):
    status: str
    output: str


def out(t: ScheduledTask) -> TaskOut:
    return TaskOut.model_validate(t, from_attributes=True)


@router.get("/{app_id}/tasks")
async def list_tasks(app_id: int, _: Operator, rt: RuntimeDep) -> TasksOut:
    tasks = [out(t) for t in await TaskTools(rt).list(app_id)]
    async with rt.sessions() as session:
        app, entry, _c = await rt.apps.main_container(session, app_id)
    game = entry.template.game if entry else None
    return TasksOut(timezone=rt.settings.timezone, services=[s.name for s in app.services],
                    console=bool(game and game.console), tasks=tasks)  # fmt: skip


@router.post("/{app_id}/tasks", status_code=201)
async def create(app_id: int, body: TaskIn, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    return {"id": await TaskTools(rt).save(app_id, body.model_dump())}


@router.put("/{app_id}/tasks/{task_id}", status_code=204)
async def update(app_id: int, task_id: int, body: TaskIn, _: Operator, rt: RuntimeDep) -> None:
    await TaskTools(rt).save(app_id, body.model_dump(), task_id)


@router.delete("/{app_id}/tasks/{task_id}", status_code=204)
async def delete(app_id: int, task_id: int, _: Operator, rt: RuntimeDep) -> None:
    await TaskTools(rt).delete(app_id, task_id)


@router.post("/{app_id}/tasks/{task_id}/run")
async def run_now(app_id: int, task_id: int, _: Operator, rt: RuntimeDep) -> RunOut:
    status, output = await TaskTools(rt).run(app_id, task_id)
    return RunOut(status=status, output=output[-4000:])
