"""Job routes (/api/v1/jobs)."""

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from hivora.core.errors import NotFoundError
from hivora.jobs.models import Job, JobKind, JobStatus
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["jobs"])


class JobOut(BaseModel):
    id: int
    kind: JobKind
    status: JobStatus
    app_id: int | None
    app_slug: str | None
    progress: int
    error: str | None
    created_by: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobDetailOut(JobOut):
    log: str


def job_out(j: Job) -> JobOut:
    return JobOut(
        id=j.id,
        kind=j.kind,
        status=j.status,
        app_id=j.app_id,
        app_slug=j.app_slug,
        progress=j.progress,
        error=j.error,
        created_by=j.created_by,
        created_at=j.created_at,
        started_at=j.started_at,
        finished_at=j.finished_at,
    )


@router.get("")
async def list_jobs(
    _: Viewer, rt: RuntimeDep, app_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[JobOut]:  # fmt: skip
    query = select(Job).order_by(Job.id.desc()).limit(limit)
    if app_id is not None:
        query = query.where(Job.app_id == app_id)
    async with rt.sessions() as session:
        return [job_out(j) for j in await session.scalars(query)]


@router.get("/{job_id}")
async def get_job(job_id: int, _: Viewer, rt: RuntimeDep) -> JobDetailOut:
    async with rt.sessions() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise NotFoundError("job not found")
        return JobDetailOut(**job_out(job).model_dump(), log=job.log)


@router.post("/{job_id}/cancel", status_code=202)
async def cancel_job(job_id: int, _: Operator, rt: RuntimeDep) -> None:
    await rt.jobs.cancel(job_id)
