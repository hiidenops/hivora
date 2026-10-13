"""Start, stop or restart a zone's apps in the order of their dependencies.

The dependencies (``app_dependency``) say which app starts after which, within a zone; the
order is computed by ``apps.start_order``. An action is one ``zone_action`` job that drives the
apps' own jobs (their lock, log and audit unchanged), wave by wave:

- start: each wave starts the apps whose dependencies are all healthy, waits for each app's
  job, then for the app to be healthy (the zone's timeout, counted once the job is done: a
  wait in the queue does not count). An app that fails holds back the apps that need it; the
  other branches go on. The job fails at the end, naming them.
- stop: the waves backwards; an app stops once the apps that need it are stopped.
- restart: the whole zone stopped, then started.

One zone action at a time: the job waits for the apps' jobs, which need a free worker (the
queue has 2 by default; with a single one, they would never run).
"""

import asyncio
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hivora.apps.start_order as start_order
from hivora.apps.lifecycle import Lifecycle
from hivora.apps.models import AppDependency, Application, Origin
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.jobs.models import JobStatus
from hivora.jobs.queries import get_job
from hivora.state import AppStatus, StateStore
from hivora.zones.service import get_zone

Action = Literal["start", "stop", "restart"]
POLL_S = 0.5
RUNNING = frozenset({AppStatus.HEALTHY})
DOWN = frozenset({AppStatus.STOPPED, AppStatus.MISSING})
_DONE = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED)


class ZoneActionRunningError(ConflictError):
    code = "zone_action_running"


class ZoneActionFailedError(ConflictError):
    code = "zone_action_failed"


@dataclass(frozen=True, slots=True)
class Member:
    id: int
    slug: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class Startup:
    zone: str
    timeout_s: int
    apps: list[Member]
    dependencies: list[start_order.Dependency]
    steps: list[list[int]]


class ZoneActions:
    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], jobs: JobQueue,
        lifecycle: Lifecycle, store: StateStore, bus: EventBus,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.jobs = jobs
        self.lifecycle = lifecycle
        self.store = store
        self.bus = bus

    def register(self) -> None:
        self.jobs.register(JobKind.ZONE_ACTION, self._run)

    # --- the zone's start order --------------------------------------------------------
    async def startup(self, slug: str) -> Startup:
        async with self.sessions() as session:
            zone = await get_zone(session, slug)
            apps = await _members(session, zone.id)
            deps = await _dependencies(session, [a.id for a in apps])
        ids = [a.id for a in apps]
        return Startup(zone.slug, zone.start_timeout_s,
                       [Member(a.id, a.slug, a.name, self.store.app(a.slug).status.value)
                        for a in apps],
                       deps, start_order.steps(ids, deps))  # fmt: skip

    async def set_startup(self, slug: str, dependencies: list[start_order.Dependency],
                          timeout_s: int) -> Startup:  # fmt: skip
        """Replace the zone's dependencies (checked: same zone, no loop) and its timeout."""
        async with self.sessions() as session, session.begin():
            zone = await get_zone(session, slug)
            ids = [a.id for a in await _members(session, zone.id)]
            valid = start_order.check(ids, dependencies)
            await session.execute(delete(AppDependency).where(AppDependency.app_id.in_(ids)))
            session.add_all(AppDependency(app_id=a, depends_on_id=d) for a, d in valid)
            zone.start_timeout_s = timeout_s
        self.bus.publish("zone.start_order_changed", target=slug, dependencies=len(valid),
                         timeout_s=timeout_s)  # fmt: skip
        return await self.startup(slug)

    async def request(self, slug: str, action: Action) -> Job:
        async with self.sessions() as session, session.begin():
            zone = await get_zone(session, slug)
            busy = await session.scalar(select(Job.id).where(
                Job.kind == JobKind.ZONE_ACTION,
                Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING))).limit(1))  # fmt: skip
            if busy is not None:
                raise ZoneActionRunningError("a zone action is already running", job=busy)
            job = self.jobs.add(session, JobKind.ZONE_ACTION,
                                params={"zone": zone.slug, "action": action})  # fmt: skip
        self.jobs.wake()
        self.bus.publish("zone.action_requested", target=slug, action=action, job=job.id)
        return job

    # --- the job ----------------------------------------------------------------------------
    async def _run(self, ctx: JobContext) -> None:
        slug, action = str(ctx.params["zone"]), str(ctx.params["action"])
        async with self.sessions() as session:  # read, then closed before any wait
            zone = await get_zone(session, slug)
            apps = {a.id: a.slug for a in await _members(session, zone.id)}
            deps = await _dependencies(session, list(apps))
            limit_s = zone.start_timeout_s
        problems: list[str] = []
        if action in ("stop", "restart"):
            problems += await self._waves(ctx, apps, [(d, a) for a, d in deps], "stop", limit_s)
        if action in ("start", "restart"):
            problems += await self._waves(ctx, apps, deps, "start", limit_s)
        self.bus.publish("zone.action_done", target=slug, action=action, problems=len(problems))
        if problems:
            raise ZoneActionFailedError("; ".join(problems)[-500:], zone=slug)

    async def _waves(self, ctx: JobContext, apps: dict[int, str],
                     deps: list[start_order.Dependency], how: Literal["start", "stop"],
                     limit_s: int) -> list[str]:  # fmt: skip
        """``deps`` read "a goes after b": to stop, the zone's dependencies reversed."""
        needs: dict[int, set[int]] = {a: set() for a in apps}
        for a, b in deps:
            needs[a].add(b)
        pending, done, failed = set(apps), set[int](), set[int]()
        problems: list[str] = []
        wave = 0
        while ready := sorted(a for a in pending if needs[a] <= done):
            wave += 1
            await ctx.log(f"{how}, wave {wave}: {', '.join(apps[a] for a in ready)}")
            started = [await (self.lifecycle.start if how == "start" else self.lifecycle.stop)(a)
                       for a in ready]  # fmt: skip
            want = RUNNING if how == "start" else DOWN
            pairs = zip(ready, started, strict=True)
            results = await asyncio.gather(*(self._settled(apps[a], job.id, want, limit_s)
                                             for a, job in pairs))  # fmt: skip
            for a, problem in zip(ready, results, strict=True):
                pending.discard(a)
                if problem is None:
                    done.add(a)
                    await ctx.log(f"  {apps[a]}: {'healthy' if how == 'start' else 'stopped'}")
                else:
                    failed.add(a)
                    problems.append(f"{apps[a]}: {problem}")
                    await ctx.log(f"  {apps[a]}: {problem}")
        for a in sorted(pending):  # held back by an app that failed
            waits = ", ".join(apps[b] for b in sorted(needs[a] & failed or needs[a]))
            problems.append(f"{apps[a]}: not {how}ed, waits for {waits}")
            await ctx.log(f"  {apps[a]}: held back")
        return problems

    async def _settled(self, slug: str, job_id: int, want: frozenset[AppStatus],
                       limit_s: int) -> str | None:  # fmt: skip
        """None once the app's job succeeded and the app reached ``want``; else why not."""
        while True:  # the app's own job: its wait in the queue does not count
            async with self.sessions() as session:
                job = await get_job(session, job_id)
                status, error = (job.status, job.error) if job else (JobStatus.CANCELLED, None)
            if status in _DONE:
                break
            await asyncio.sleep(POLL_S)
        if status is not JobStatus.SUCCEEDED:
            return f"its job {status.value}" + (f" ({error})" if error else "")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + limit_s
        while (now := self.store.app(slug).status) not in want:
            if loop.time() >= deadline:
                return f"still {now.value} after {limit_s} s"
            await asyncio.sleep(POLL_S)
        return None


async def _members(session: AsyncSession, zone_id: int) -> list[Application]:
    """The zone's apps that can start (deployed, or adopted), by name."""
    rows = await session.scalars(select(Application).where(Application.zone_id == zone_id)
                                 .order_by(Application.name))  # fmt: skip
    return [a for a in rows if a.current_revision_id is not None or a.origin is Origin.ADOPTED]


async def _dependencies(session: AsyncSession, ids: list[int]) -> list[start_order.Dependency]:
    """The dependencies between these apps (others, e.g. on an undeployed app, ignored)."""
    rows = await session.execute(select(AppDependency.app_id, AppDependency.depends_on_id)
                                 .where(AppDependency.app_id.in_(ids),
                                        AppDependency.depends_on_id.in_(ids)))  # fmt: skip
    return sorted((a, d) for a, d in rows.tuples())
