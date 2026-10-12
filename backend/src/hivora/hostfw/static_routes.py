"""Static IPv4 routes: the intention in SQLite, applied to the host by a job.

Adding a route reads the host's routing table first (through the agent, no transaction open),
refuses what could cut the host off (``routing.check``), then records the row and a
``host_route`` job in one short transaction; removing one is a row deleted and a job. The job,
one at a time under the instance's lock, reads the table afresh, deletes the routes marked
proto 241 that are no longer wanted, checks each wanted route again against the network as it
is now, and sets the others (``ip route replace``, idempotent). A route refused by ``ip`` or
set aside fails the job once the others are set: the intention stays. Routes without the mark
(DHCP, the kernel, Docker, by hand) are never touched. A reboot empties them: Hivora queues
the job again when it starts.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.clock import Clock
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.hostfw import routing
from hivora.hostfw.models import StaticRoute
from hivora.hostfw.service import AgentOffError, HostCommandError, HostFirewall
from hivora.jobs import Job, JobContext, JobKind, JobQueue


class RouteExistsError(ConflictError):
    code = "route_exists"


class RouteNotFoundError(NotFoundError):
    code = "route_not_found"


@dataclass(frozen=True, slots=True)
class Listed:
    id: int
    destination: str
    gateway: str
    dev: str | None
    metric: int | None
    note: str | None
    created_by: int | None
    created_at: datetime
    applied: bool | None  # on the host now; None: unknown (agent off, table unreadable)


class StaticRoutes:
    def __init__(
        self, *, fw: HostFirewall, sessions: async_sessionmaker[AsyncSession], jobs: JobQueue,
        bus: EventBus, clock: Clock,
    ) -> None:  # fmt: skip
        self.fw = fw
        self.sessions = sessions
        self.jobs = jobs
        self.bus = bus
        self.clock = clock
        self._lock = asyncio.Lock()  # one apply at a time: the last reads the table last

    def register(self) -> None:
        self.jobs.register(JobKind.HOST_ROUTE, self._apply)

    async def listing(self) -> list[Listed]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(StaticRoute).order_by(StaticRoute.id))).all()
        present: set[str] | None = None  # unknown: the agent off, or the table unreadable
        if rows and await self.fw.agent_enabled():
            try:
                present = set(routing.marked(await self._table(routing.SHOW)))
            except HostCommandError:
                present = None
        return [Listed(r.id, r.destination, r.gateway, r.dev, r.metric, r.note, r.created_by,
                       r.created_at, None if present is None else r.destination in present)
                for r in rows]  # fmt: skip

    async def add(self, destination: str, gateway: str, *, dev: str | None, metric: int | None,
                  note: str | None, requester: str | None, user_id: int | None) -> Job:  # fmt: skip
        r = routing.route(destination, gateway, dev, metric)
        # Reading the table goes through the agent: off, it refuses (host_agent_off).
        routing.check(r, routing.connected(await self._table(routing.ALL)), requester=requester)
        async with self.sessions() as session, session.begin():
            if await self._find(session, r.destination) is not None:
                raise RouteExistsError("a route to this network exists", destination=r.destination)
            session.add(StaticRoute(destination=r.destination, gateway=r.gateway, dev=r.dev,
                                    metric=r.metric, note=note or None, created_by=user_id,
                                    created_at=self.clock.now()))  # fmt: skip
            job = self.jobs.add(session, JobKind.HOST_ROUTE)
        self.jobs.wake()
        self.bus.publish("hostfw.route_added", target=r.destination, gateway=r.gateway, job=job.id)
        return job

    async def remove(self, route_id: int) -> Job:
        await self._agent_on()
        async with self.sessions() as session, session.begin():
            row = await session.get(StaticRoute, route_id)
            if row is None:
                raise RouteNotFoundError("no such route", id=route_id)
            destination = row.destination
            await session.delete(row)
            job = self.jobs.add(session, JobKind.HOST_ROUTE)
        self.jobs.wake()
        self.bus.publish("hostfw.route_removed", target=destination, job=job.id)
        return job

    async def reapply(self) -> Job | None:
        """At startup: the host may have rebooted (its routes gone). No route, or the agent
        off: nothing queued."""
        if not await self.fw.agent_enabled():
            return None
        async with self.sessions() as session, session.begin():
            if await session.scalar(select(StaticRoute.id).limit(1)) is None:
                return None
            job = self.jobs.add(session, JobKind.HOST_ROUTE)
        self.jobs.wake()
        return job

    # --- the job --------------------------------------------------------------------
    async def _apply(self, ctx: JobContext) -> None:
        async with self._lock:
            async with self.sessions() as session:  # read, then closed before any command
                rows = (await session.scalars(select(StaticRoute))).all()
                wanted = [routing.Route(r.destination, r.gateway, r.dev, r.metric) for r in rows]
            host = routing.connected(await self._table(routing.ALL))
            keep, stale = routing.plan(wanted, await self._table(routing.SHOW))
            problems: list[str] = []
            await ctx.progress(20, "ip route del")
            for destination in stale:
                code, out = await self.fw._run(routing.delete_argv(destination), check=False)
                await ctx.log(f"removed {destination}" if code == 0 else f"{destination}: {out}")
                if code != 0:
                    problems.append(f"{destination}: {out.strip()[-200:]}")
            await ctx.progress(50, "ip route replace")
            applied = 0
            for r in keep:
                try:  # the network may have changed since the route was added
                    routing.check(r, host, requester=None)
                except ConflictError as e:
                    await ctx.log(f"{r.destination}: set aside ({e.code})")
                    problems.append(f"{r.destination}: {e.code}")
                    continue
                code, out = await self.fw._run(routing.replace_argv(r), check=False)
                if code != 0:
                    await ctx.log(f"{r.destination}: {out.strip()}")
                    problems.append(f"{r.destination}: {out.strip()[-200:]}")
                    continue
                applied += 1
                await ctx.log(f"{r.destination} via {r.gateway}")
        self.bus.publish("hostfw.routes_applied", target="proto 241", applied=applied,
                         removed=len(stale), failed=len(problems))  # fmt: skip
        if problems:
            output = "; ".join(problems)[-500:]
            raise HostCommandError("some routes were not applied", output=output)

    # --- helpers --------------------------------------------------------------------
    async def _table(self, argv: list[str]) -> list[dict[str, Any]]:
        code, out = await self.fw._run(argv, check=False)
        try:
            rows = json.loads(out or "[]") if code == 0 else None
        except ValueError:
            rows = None
        if not isinstance(rows, list):
            raise HostCommandError("the host's routing table could not be read", output=out[-500:])
        return [r for r in rows if isinstance(r, dict)]

    async def _agent_on(self) -> None:
        if not await self.fw.agent_enabled():
            raise AgentOffError("the host agent is off (Settings → host firewall)")

    @staticmethod
    async def _find(session: AsyncSession, destination: str) -> StaticRoute | None:
        found: StaticRoute | None = await session.scalar(
            select(StaticRoute).where(StaticRoute.destination == destination)
        )
        return found
