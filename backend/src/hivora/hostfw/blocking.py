"""Blocked addresses: the intention in SQLite, applied to the host by a job.

A block (or unblock) is a row and a ``host_firewall`` job, in one short transaction. The job
rebuilds the whole HIVORA-BLOCK chain from the table (``blocklist.restore_text``, through
``iptables-restore --noflush``: the chain changes at once, no other chain is touched), then
makes sure INPUT (the host's services) and DOCKER-USER (the apps Docker publishes) jump to it
first. The jobs run one at a time under the instance's lock, each reading the table afresh:
the last one applies the table as it is. A host's reboot empties its rules: Hivora queues the
job again when it starts. Turning the agent off leaves the rules on the host.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.clock import Clock
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.hostfw.blocklist import (
    CHAIN,
    Family,
    InvalidAddressError,
    restore_text,
    split,
    valid_address,
)
from hivora.hostfw.models import BlockedAddress
from hivora.hostfw.service import AgentOffError, HostCommandError, HostFirewall
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.state import StateStore

# The chains that jump to HIVORA-BLOCK, first: the host's own services, then the packets
# Docker forwards to the apps (they keep the client's address after Docker's NAT).
CALLERS = ("INPUT", "DOCKER-USER")
FAMILIES: tuple[Family, Family] = (4, 6)
TOOLS: dict[Family, tuple[str, str]] = {4: ("iptables", "iptables-restore"),
                                        6: ("ip6tables", "ip6tables-restore")}  # fmt: skip
# The rules, generated here from validated addresses, passed as an argument to a fixed script.
RESTORE = 'printf "%s" "$1" | {} --noflush'


class AlreadyBlockedError(ConflictError):
    code = "address_already_blocked"


class OwnAddressError(ConflictError):
    code = "own_address"


class HostAddressError(ConflictError):
    code = "host_address"


class NotBlockedError(NotFoundError):
    code = "address_not_blocked"


@dataclass(frozen=True, slots=True)
class Blocked:
    address: str
    note: str | None
    created_by: int | None
    created_at: datetime


class Blocking:
    def __init__(
        self, *, fw: HostFirewall, sessions: async_sessionmaker[AsyncSession], jobs: JobQueue,
        bus: EventBus, clock: Clock, store: StateStore, host_ips: Callable[[], list[str | None]],
    ) -> None:  # fmt: skip
        self.fw = fw
        self.sessions = sessions
        self.jobs = jobs
        self.bus = bus
        self.clock = clock
        self.store = store  # the containers' addresses, never blocked
        self.host_ips = host_ips  # the host's own addresses (LAN, public), never blocked
        self._lock = asyncio.Lock()  # one rebuild at a time: the last reads the table last

    def register(self) -> None:
        self.jobs.register(JobKind.HOST_FIREWALL, self._apply)

    async def listing(self) -> list[Blocked]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(BlockedAddress).order_by(BlockedAddress.id))).all()
        return [Blocked(r.address, r.note, r.created_by, r.created_at) for r in rows]

    async def block(self, address: str, note: str | None, *, requester: str | None,
                    user_id: int | None) -> Job:  # fmt: skip
        """Block one address (refused: the requester's own, the host's, a container's)."""
        ip = valid_address(address)
        if requester and _same(requester, ip):
            raise OwnAddressError("this is the address you are connected from", address=ip)
        if any(_same(own, ip) for own in self._protected()):
            raise HostAddressError("an address of this host or of its containers", address=ip)
        await self._agent_on()
        async with self.sessions() as session, session.begin():
            if await self._find(session, ip):
                raise AlreadyBlockedError("this address is already blocked", address=ip)
            session.add(BlockedAddress(address=ip, note=note or None, created_by=user_id,
                                       created_at=self.clock.now()))  # fmt: skip
            job = self.jobs.add(session, JobKind.HOST_FIREWALL)
        self.jobs.wake()
        self.bus.publish("hostfw.blocked", target=ip, job=job.id)
        return job

    async def unblock(self, address: str) -> Job:
        ip = valid_address(address)
        await self._agent_on()
        async with self.sessions() as session, session.begin():
            row = await self._find(session, ip)
            if row is None:
                raise NotBlockedError("this address is not blocked", address=ip)
            await session.delete(row)
            job = self.jobs.add(session, JobKind.HOST_FIREWALL)
        self.jobs.wake()
        self.bus.publish("hostfw.unblocked", target=ip, job=job.id)
        return job

    async def reapply(self) -> Job | None:
        """At startup: the host may have rebooted (its rules gone). Nothing blocked, or the
        agent off: nothing queued (the chain is never created on a host that does not use it)."""
        if not await self.fw.agent_enabled():
            return None
        async with self.sessions() as session, session.begin():
            if await session.scalar(select(BlockedAddress.id).limit(1)) is None:
                return None
            job = self.jobs.add(session, JobKind.HOST_FIREWALL)
        self.jobs.wake()
        return job

    # --- the job --------------------------------------------------------------------
    async def _apply(self, ctx: JobContext) -> None:
        async with self._lock:
            async with self.sessions() as session:  # read, then closed before any command
                found = (await session.scalars(select(BlockedAddress.address))).all()
            families = split(found)
            for n, family in enumerate(FAMILIES):
                await ctx.progress(10 + 45 * n, TOOLS[family][0])
                await self._family(ctx, family, families[family])
        self.bus.publish("hostfw.blocklist_applied", target=CHAIN,
                         ipv4=len(families[4]), ipv6=len(families[6]))  # fmt: skip

    async def _family(self, ctx: JobContext, family: Family, addresses: list[str]) -> None:
        tables, restore = TOOLS[family]
        code, out = await self.fw._run(["sh", "-c", RESTORE.format(restore), "hivora",
                                        restore_text(addresses, family)], check=False)  # fmt: skip
        if code != 0:
            if not addresses and _missing(code, out):  # no ip6tables, nothing to block in IPv6
                await ctx.log(f"{restore}: not on the host, no IPv{family} address to block")
                return
            raise HostCommandError(f"{restore} failed", output=out[-500:])
        await ctx.log(f"{CHAIN} (IPv{family}): {len(addresses)} address(es)")
        for chain in CALLERS:
            jump = [chain, "-j", CHAIN]
            if (await self.fw._run([tables, "-C", *jump], check=False))[0] == 0:
                continue  # already jumps to it
            code, out = await self.fw._run([tables, "-I", chain, "1", "-j", CHAIN], check=False)
            if code != 0 and chain == "DOCKER-USER" and "No chain" in out:
                await ctx.log(f"{tables}: no DOCKER-USER chain (Docker does not filter IPv"
                              f"{family} here): the host's services only")  # fmt: skip
            elif code != 0:
                raise HostCommandError(f"{tables} failed", output=out[-500:])

    # --- helpers --------------------------------------------------------------------
    async def _agent_on(self) -> None:
        if not await self.fw.agent_enabled():
            raise AgentOffError("the host agent is off (Settings → host firewall)")

    def _protected(self) -> list[str]:
        own = [ip for ip in self.host_ips() if ip]
        return own + [ip for c in self.store.containers() for ip in c.ips]

    @staticmethod
    async def _find(session: AsyncSession, ip: str) -> BlockedAddress | None:
        found: BlockedAddress | None = await session.scalar(
            select(BlockedAddress).where(BlockedAddress.address == ip)
        )
        return found


def _same(text: str, ip: str) -> bool:
    """``text`` is ``ip`` (any form: IPv4 seen through IPv6 included); not an IP: no."""
    try:
        return valid_address(text) == ip
    except InvalidAddressError:
        return False


def _missing(code: int, out: str) -> bool:
    return code == 127 or "not found" in out.lower() or "No such file" in out
