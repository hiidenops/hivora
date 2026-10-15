"""Read-only job queries for other modules, in the caller's session."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.jobs.models import Job, JobKind, JobStatus


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def last_job(session: AsyncSession, app_id: int, kind: JobKind) -> Job | None:
    """The app's most recent job of this kind (queued, running or done)."""
    job: Job | None = await session.scalar(
        select(Job).where(Job.app_id == app_id, Job.kind == kind).order_by(Job.id.desc()).limit(1)
    )
    return job


async def job_health(
    session: AsyncSession, since: datetime, stuck_before: datetime
) -> dict[str, int]:
    """Counts for the System page: running, queued, failed since ``since``, and running
    jobs started before ``stuck_before`` (probably stuck)."""

    async def count(*where: Any) -> int:
        return int(await session.scalar(select(func.count()).select_from(Job).where(*where)) or 0)

    return {
        "running": await count(Job.status == JobStatus.RUNNING),
        "queued": await count(Job.status == JobStatus.QUEUED),
        "failed": await count(Job.status == JobStatus.FAILED, Job.finished_at >= since),
        "stuck": await count(Job.status == JobStatus.RUNNING, Job.started_at < stuck_before),
    }
