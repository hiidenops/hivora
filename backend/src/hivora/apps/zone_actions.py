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
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import hivora.apps.links as links
import hivora.apps.start_order as start_order
from hivora.apps.lifecycle import Lifecycle
from hivora.apps.models import AppDependency, Application, Origin
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.docker_gateway import DockerGateway
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.jobs.models import JobStatus
from hivora.jobs.queries import get_job
from hivora.state import AppStatus, StateStore
from hivora.zones.models import Zone
from hivora.zones.service import delete_zone, get_zone

Action = Literal["start", "stop", "restart", "purge"]
POLL_S = 0.5
DEFAULT_TIMEOUT_S = 120  # apps without a zone
RUNNING = frozenset({AppStatus.HEALTHY})
DOWN = frozenset({AppStatus.STOPPED, AppStatus.MISSING})
_DONE = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED)


class ZoneActionRunningError(ConflictError):
    code = "zone_action_running"


class ZoneActionFailedError(ConflictError):
    code = "zone_action_failed"


class ZonePurgeBlockedError(ConflictError):
    code = "zone_purge_blocked"


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
        gateway: DockerGateway | None = None,
    ) -> None:  # fmt: skip
        self.gateway = gateway  # the zone's network, removed with it (purge)
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

    # --- everything in a zone removed, then the zone -------------------------------------
    async def purge_plan(self, slug: str) -> dict[str, Any]:
        """What "remove the zone and everything in it" removes: each app with its
        containers, files and data folders; and what blocks it (an app of another zone
        linked to one of these: it would lose its network)."""
        async with self.sessions() as session:
            zone = await get_zone(session, slug)
            apps = await _all_members(session, zone.id)
            inside = {a.slug for a in apps}
            catalog = self.lifecycle.planner.catalog
            tools = [t for a in apps for t in await links.linked_by(session, catalog, a.slug)]
            blocked = sorted({t.name for t in tools if t.slug not in inside})
        plans = []
        for a in apps:
            plan = await self.lifecycle.removal_plan(a.id)
            plans.append({"id": a.id, "name": a.name, "containers": plan.containers,
                          "files": plan.files, "data": plan.data})  # fmt: skip
        return {"zone": zone.slug, "name": zone.name, "system": zone.is_system,
                "apps": plans, "blocked": blocked}  # fmt: skip

    async def purge(self, slug: str, *, remove_data: bool) -> Job:
        plan = await self.purge_plan(slug)
        if plan["system"]:
            raise ZonePurgeBlockedError("the Administration zone cannot be removed", zone=slug)
        if plan["blocked"]:
            raise ZonePurgeBlockedError("apps of other zones are linked to apps of this zone",
                                        zone=slug, apps=", ".join(plan["blocked"]))  # fmt: skip
        return await self.request(slug, "purge", remove_data=remove_data)

    async def _purge(self, ctx: JobContext, slug: str, remove_data: bool) -> None:
        """Each app removed (its own job: lock, log, audit), the ones others link to after
        them; then the zone and its network."""
        async with self.sessions() as session:
            zone = await get_zone(session, slug)
            pending = {a.id: a.slug for a in await _all_members(session, zone.id)}
        problems: list[str] = []
        while pending:
            jobs, deferred = {}, {}
            for app_id, app_slug in pending.items():
                try:
                    jobs[app_id] = await self.lifecycle.remove(app_id, remove_data=remove_data)
                except links.LinkedAppError:
                    deferred[app_id] = app_slug  # a tool of the zone still links it: next round
            if not jobs:
                problems += [f"{s}: still linked" for s in deferred.values()]
                break
            await ctx.log(f"removing: {', '.join(pending[a] for a in jobs)}")
            for app_id, job in jobs.items():
                problem = await self._job_done(job.id)
                await ctx.log(f"  {pending[app_id]}: {problem or 'removed'}")
                if problem:
                    problems.append(f"{pending[app_id]}: {problem}")
            if problems:
                break
            pending = deferred
        if problems:
            raise ZoneActionFailedError("; ".join(problems)[-500:], zone=slug)
        async with self.sessions() as session, session.begin():
            await delete_zone(session, slug, 0)
        if self.gateway is not None:
            await self.gateway.remove_network(f"hivora-zone-{slug}")
        await ctx.log(f"zone {slug} removed")
        self.bus.publish("zone.deleted", target=slug, purged=True, data_removed=remove_data)

    async def _job_done(self, job_id: int) -> str | None:
        """None once the job succeeded; else why not."""
        while True:
            async with self.sessions() as session:
                job = await get_job(session, job_id)
                status, error = (job.status, job.error) if job else (JobStatus.CANCELLED, None)
            if status in _DONE:
                break
            await asyncio.sleep(POLL_S)
        if status is JobStatus.SUCCEEDED:
            return None
        return f"its job {status.value}" + (f" ({error})" if error else "")

    async def request(self, slug: str, action: Action, *, remove_data: bool = False) -> Job:
        async with self.sessions() as session, session.begin():
            zone = await get_zone(session, slug)
            busy = await session.scalar(select(Job.id).where(
                Job.kind == JobKind.ZONE_ACTION,
                Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING))).limit(1))  # fmt: skip
            if busy is not None:
                raise ZoneActionRunningError("a zone action is already running", job=busy)
            params: dict[str, Any] = {"zone": zone.slug, "action": action}
            if action == "purge":
                params["remove_data"] = remove_data
            job = self.jobs.add(session, JobKind.ZONE_ACTION, params=params)
        self.jobs.wake()
        self.bus.publish("zone.action_requested", target=slug, action=action, job=job.id)
        return job

    # --- the job ----------------------------------------------------------------------------
    async def _run(self, ctx: JobContext) -> None:
        slug, action = str(ctx.params["zone"]), str(ctx.params["action"])
        if action == "purge":
            await self._purge(ctx, slug, bool(ctx.params.get("remove_data")))
            return
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

    async def apps_in_order(self, ctx: JobContext, ids: list[int],
                            how: Literal["start", "stop"]) -> list[str]:  # fmt: skip
        """Start or stop these apps (any zones) in their zones' dependency order, waiting for
        each one like a zone action (the longest zone timeout); the problems met."""
        async with self.sessions() as session:
            rows = (await session.scalars(select(Application).where(Application.id.in_(ids)))).all()
            apps = {a.id: a.slug for a in rows}
            deps = await _dependencies(session, list(apps))
            zones = {a.zone_id for a in rows if a.zone_id}
            limits = [z.start_timeout_s for z in (await session.scalars(
                select(Zone).where(Zone.id.in_(zones)))).all()]  # fmt: skip
        limit_s = max(limits, default=DEFAULT_TIMEOUT_S)
        order = deps if how == "start" else [(d, a) for a, d in deps]
        return await self._waves(ctx, apps, order, how, limit_s)

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


async def _all_members(session: AsyncSession, zone_id: int) -> list[Application]:
    """Every app of the zone, deployed or not, by name."""
    rows = await session.scalars(select(Application).where(Application.zone_id == zone_id)
                                 .order_by(Application.name))  # fmt: skip
    return list(rows)


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
