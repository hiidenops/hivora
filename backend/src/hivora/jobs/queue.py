"""Persisted job queue with in-process asyncio workers.

- Jobs of the same app run strictly one after another, in creation order;
  jobs of different apps run concurrently (``workers`` at a time).
- On startup, jobs left running by a crash become ``interrupted``, except
  idempotent kinds (``resumable``) which are queued again.
- Job logs are redacted (secrets registered on the context) and capped.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.clock import Clock, SystemClock
from hivora.core.context import Actor, current_actor
from hivora.core.errors import HivoraError, NotFoundError
from hivora.core.events import EventBus
from hivora.core.redact import Redactor
from hivora.jobs.models import Job, JobKind, JobStatus

logger = logging.getLogger(__name__)

MAX_LOG_CHARS = 200_000
_FLUSH_EVERY_S = 1.0
_IDLE_POLL_S = 5.0


class JobContext:
    """What a handler sees: its parameters, and ways to report progress."""

    def __init__(self, queue: "JobQueue", job: Job) -> None:
        self._queue = queue
        self.job_id = job.id
        self.kind = job.kind
        self.app_id = job.app_id
        self.app_slug = job.app_slug
        self.params: dict[str, Any] = dict(job.params)
        self._secrets: set[str] = set()
        self._redact = Redactor()
        self._pending: list[str] = []
        self._log_size = 0
        self._last_flush = 0.0
        self.progress_value = 0

    def add_secrets(self, values: Iterable[str]) -> None:
        self._secrets.update(values)
        self._redact = Redactor(self._secrets)

    def redact(self, text: str) -> str:
        return self._redact(text)

    async def log(self, line: str) -> None:
        line = self._redact(line.rstrip("\n"))
        self._queue.bus.publish("job.log", id=self.job_id, line=line)
        if self._log_size < MAX_LOG_CHARS:
            self._pending.append(line + "\n")
            self._log_size += len(line) + 1
            if self._log_size >= MAX_LOG_CHARS:
                self._pending.append("[log truncated]\n")
        now = asyncio.get_running_loop().time()
        if now - self._last_flush >= _FLUSH_EVERY_S:
            await self.flush()

    async def progress(self, percent: int, message: str | None = None) -> None:
        self.progress_value = max(0, min(100, percent))
        self._queue.bus.publish(
            "job.progress",
            id=self.job_id,
            progress=self.progress_value,
            message=self._redact(message) if message else None,
        )
        if message:
            await self.log(message)

    async def flush(self) -> None:
        chunk, self._pending = "".join(self._pending), []
        self._last_flush = asyncio.get_running_loop().time()
        async with self._queue.sessions() as session, session.begin():
            job = await session.get_one(Job, self.job_id)
            job.log += chunk
            job.progress = self.progress_value


Handler = Callable[[JobContext], Awaitable[None]]


class JobQueue:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        bus: EventBus,
        *,
        clock: Clock | None = None,
        workers: int = 2,
        resumable: frozenset[JobKind] = frozenset({JobKind.DEPLOY}),
    ) -> None:
        self.sessions = sessions
        self.bus = bus
        self.clock = clock or SystemClock()
        self._workers = workers
        self._resumable = resumable
        self._handlers: dict[JobKind, Handler] = {}
        self._busy_apps: set[int] = set()
        self._running: dict[int, asyncio.Task[None]] = {}
        self._claim_lock = asyncio.Lock()
        self._wakeup = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = False

    def register(self, kind: JobKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    # --- producer side ----------------------------------------------------
    def add(
        self,
        session: AsyncSession,
        kind: JobKind,
        *,
        app_id: int | None = None,
        app_slug: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Job:
        """Add a job to the caller's transaction (atomic with its other writes).

        Call ``wake()`` once the transaction is committed.
        """
        job = Job(
            kind=kind,
            app_id=app_id,
            app_slug=app_slug,
            params=params or {},
            status=JobStatus.QUEUED,
            progress=0,
            log="",
            created_at=self.clock.now(),
        )
        session.add(job)
        return job

    def wake(self) -> None:
        self._wakeup.set()

    async def cancel(self, job_id: int) -> None:
        async with self.sessions() as session, session.begin():
            job = await session.get(Job, job_id)
            if job is None:
                raise NotFoundError("job not found", id=job_id)
            if job.status is JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.finished_at = self.clock.now()
                self.bus.publish("job.finished", id=job.id, status=job.status.value)
                return
        if task := self._running.get(job_id):
            task.cancel()

    # --- history (read by the job routes) ------------------------------------
    async def recent(self, app_id: int | None, limit: int) -> list[Job]:
        """The newest jobs first, of one app or of all."""
        query = select(Job).order_by(Job.id.desc()).limit(limit)
        if app_id is not None:
            query = query.where(Job.app_id == app_id)
        async with self.sessions() as session:
            return list(await session.scalars(query))

    async def get(self, job_id: int) -> Job:
        async with self.sessions() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise NotFoundError("job not found")
            return job

    async def clear_finished(self) -> int:
        """Delete finished jobs and their logs; queued and running ones are kept."""
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                delete(Job).where(Job.status.not_in((JobStatus.QUEUED, JobStatus.RUNNING)))
            )
        deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]
        self.bus.publish("jobs.cleared", deleted=deleted)
        return deleted

    # --- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        await self.recover()
        self._tasks = [
            asyncio.create_task(self._worker(), name=f"job-worker-{i}")
            for i in range(self._workers)
        ]
        self.wake()

    async def stop(self) -> None:
        """Running jobs stay ``running`` in the database: ``recover()`` handles them."""
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        self._stopping = False

    async def recover(self) -> None:
        async with self.sessions() as session, session.begin():
            stale = (await session.scalars(
                select(Job).where(Job.status == JobStatus.RUNNING)
            )).all()  # fmt: skip
            for job in stale:
                if job.kind in self._resumable:
                    job.status = JobStatus.QUEUED
                    job.log += "[resumed after restart]\n"
                else:
                    job.status = JobStatus.INTERRUPTED
                    job.error = "interrupted by a restart of Hivora"
                    job.finished_at = self.clock.now()

    # --- consumer side ------------------------------------------------------
    async def _worker(self) -> None:
        while True:
            self._wakeup.clear()
            job = await self._claim()
            if job is None:
                with suppress(TimeoutError):
                    async with asyncio.timeout(_IDLE_POLL_S):
                        await self._wakeup.wait()
                continue
            task = asyncio.create_task(self._run(job))
            self._running[job.id] = task
            try:
                await task
            finally:
                self._running.pop(job.id, None)
                if job.app_id is not None:
                    self._busy_apps.discard(job.app_id)
                self.wake()  # a job of the same app may be waiting

    async def _claim(self) -> Job | None:
        async with self._claim_lock, self.sessions() as session, session.begin():
            queued = await session.scalars(
                select(Job).where(Job.status == JobStatus.QUEUED).order_by(Job.id)
            )
            seen_apps: set[int] = set()
            for job in queued:
                if job.app_id is not None:
                    # FIFO per app: only the oldest queued job of an app is eligible.
                    if job.app_id in self._busy_apps or job.app_id in seen_apps:
                        seen_apps.add(job.app_id)
                        continue
                    self._busy_apps.add(job.app_id)
                job.status = JobStatus.RUNNING
                job.started_at = self.clock.now()
                return job
        return None

    async def _run(self, job: Job) -> None:
        # Events published by the handler are attributed to the job's creator.
        current_actor.set(Actor(user_id=job.created_by) if job.created_by else None)
        ctx = JobContext(self, job)
        self.bus.publish("job.started", id=job.id, kind=job.kind.value, app=job.app_slug)
        status, error = JobStatus.SUCCEEDED, None
        try:
            handler = self._handlers.get(job.kind)
            if handler is None:
                raise HivoraError(f"no handler for job kind {job.kind.value}")
            await handler(ctx)
            ctx.progress_value = 100
        except asyncio.CancelledError:
            if self._stopping:
                raise  # shutdown: leave it running, recover() decides on restart
            status, error = JobStatus.CANCELLED, "cancelled"
        except Exception as exc:
            status, error = JobStatus.FAILED, ctx.redact(str(exc)) or type(exc).__name__
            if not isinstance(exc, HivoraError):
                logger.exception("job crashed", extra={"job": job.id, "kind": job.kind.value})
            await ctx.log(f"error: {error}")
        await ctx.flush()
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(Job).where(Job.id == job.id).values(
                    status=status, error=error, finished_at=self.clock.now()
                )
            )  # fmt: skip
        self.bus.publish(
            "job.finished", id=job.id, status=status.value, error=error, app=job.app_slug
        )
