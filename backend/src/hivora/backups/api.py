"""Backup routes, mounted under /api/v1/apps: /{app_id}/backups/..."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from hivora.apps.api import JobRef, job_ref
from hivora.backups.models import Backup, BackupSchedule
from hivora.backups.service import BackupNotFoundError, BackupService
from hivora.web.deps import Operator, RuntimeDep

router = APIRouter(tags=["backups"])


class ScheduleIO(BaseModel):
    enabled: bool = False
    frequency: Literal["daily", "weekly", "hours"] = "daily"
    hour: int = Field(default=4, ge=0, le=23)  # local time of the server (HIVORA_TIMEZONE)
    minute: int = Field(default=0, ge=0, le=59)
    weekday: int = Field(default=0, ge=0, le=6)  # weekly: 0 = Monday
    every_hours: int = Field(default=6, ge=1, le=168)
    keep: int = Field(default=7, ge=1, le=365)  # scheduled backups kept
    stop: bool = True  # stop the app while archiving (consistent data)


class BackupOut(BaseModel):
    id: int
    created_at: datetime
    scheduled: bool
    status: str  # pending, ok, failed
    name: str
    size: int


class BackupsOut(BaseModel):
    schedule: ScheduleIO
    next_run_at: datetime | None
    timezone: str
    volumes: list[str]  # what a backup holds
    backups: list[BackupOut]


def tools(rt: RuntimeDep) -> BackupService:
    return rt.backups


@router.get("/{app_id}/backups")
async def overview(app_id: int, _: Operator, rt: RuntimeDep) -> BackupsOut:
    b = tools(rt)
    async with rt.sessions() as session:
        app = await rt.apps.get(session, app_id)
        schedule = await session.get(BackupSchedule, app_id)
        rows = await session.scalars(
            select(Backup).where(Backup.app_id == app_id).order_by(Backup.created_at.desc())
        )
        backups = [BackupOut(id=r.id, created_at=r.created_at, scheduled=r.scheduled,
                             status=r.status, name=Path(r.path).name, size=r.size)
                   for r in rows]  # fmt: skip
        volumes = sorted(await b.volumes(app))
    io = ScheduleIO.model_validate(schedule, from_attributes=True) if schedule else ScheduleIO()
    return BackupsOut(schedule=io, next_run_at=schedule.next_run_at if schedule else None,
                      timezone=rt.settings.timezone, volumes=volumes, backups=backups)  # fmt: skip


@router.put("/{app_id}/backups/schedule")
async def set_schedule(app_id: int, body: ScheduleIO, _: Operator, rt: RuntimeDep) -> ScheduleIO:
    await tools(rt).set_schedule(app_id, **body.model_dump())
    return body


@router.post("/{app_id}/backups", status_code=202)
async def backup_now(app_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await tools(rt).request(app_id))


@router.get("/{app_id}/backups/{backup_id}/download")
async def download(app_id: int, backup_id: int, _: Operator, rt: RuntimeDep) -> FileResponse:
    async with rt.sessions() as session:
        backup = await tools(rt).get(session, app_id, backup_id)
    path = Path(backup.path)
    if backup.status != "ok" or not await asyncio.to_thread(path.is_file):
        raise BackupNotFoundError("backup file missing", id=backup_id)
    rt.bus.publish("backup.downloaded", app_id=app_id, target=path.name)
    return FileResponse(path, media_type="application/gzip", filename=path.name)


@router.post("/{app_id}/backups/{backup_id}/restore", status_code=202)
async def restore(app_id: int, backup_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    """Replace the app's volumes with this backup (the app is stopped meanwhile)."""
    return job_ref(await tools(rt).restore(app_id, backup_id))


@router.delete("/{app_id}/backups/{backup_id}", status_code=204)
async def delete(app_id: int, backup_id: int, _: Operator, rt: RuntimeDep) -> None:
    await tools(rt).delete(app_id, backup_id)
