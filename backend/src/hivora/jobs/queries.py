"""Read-only job queries for other modules, in the caller's session."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.jobs.models import Job, JobKind


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def last_job(session: AsyncSession, app_id: int, kind: JobKind) -> Job | None:
    """The app's most recent job of this kind (queued, running or done)."""
    job: Job | None = await session.scalar(
        select(Job).where(Job.app_id == app_id, Job.kind == kind).order_by(Job.id.desc()).limit(1)
    )
    return job
