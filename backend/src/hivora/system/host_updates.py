"""The host's packages (apt) and its reboot, through the host agent (exception of 03/11/2026).

Fixed command lines only, nothing from the user (CLAUDE.md, "Sécurité"):

- check (every 6 h while the agent is on, or on a click): ``apt-get update``, then
  ``apt-get -s upgrade`` (a simulation: what ``upgrade`` would install), and whether the
  host asks for a reboot (``/var/run/reboot-required``, or a kernel newer than the running
  one in ``/lib/modules``). Kept in memory: it is the host's state, not an intention.
- upgrade (job ``host_upgrade``): ``apt-get upgrade`` in a transient systemd unit of the
  host, ``hivora-apt-upgrade``, so that it goes on if the upgrade restarts Docker (and the
  agent with it); the job follows the unit until it ends, and again after a restart.
- reboot (job ``host_reboot``): the Hivora apps that run are stopped in their zones' order
  reversed (``docker compose stop``, so Docker does not start them by itself at boot) and
  noted in ``host-reboot.json``; then ``systemctl reboot``. Hivora's container comes back by
  its restart policy, the same job resumes and starts those apps again in their zones'
  order. Refused when Docker does not start at boot (``systemctl is-enabled docker``).
"""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.models import Application, Origin
from hivora.apps.zone_actions import DOWN, ZoneActions
from hivora.core.clock import Clock
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.hostfw.connections import APT
from hivora.hostfw.service import HostFirewall
from hivora.jobs import Job, JobContext, JobKind, JobQueue
from hivora.jobs.models import JobStatus
from hivora.state import StateStore

logger = logging.getLogger(__name__)

APT_UPDATE = [*APT, "-o", "DPkg::Lock::Timeout=120", "update"]
SIMULATE = ["env", "LC_ALL=C", "apt-get", "-s", "upgrade"]
REBOOT_FLAG = ["test", "-e", "/var/run/reboot-required"]
RUNNING_KERNEL = ["uname", "-r"]
KERNELS = ["ls", "-1", "/lib/modules"]
UNIT = "hivora-apt-upgrade"
UNIT_LOG = "/var/log/hivora-apt-upgrade.log"
UPGRADE = [
    "systemd-run", f"--unit={UNIT}", "--property=RemainAfterExit=yes",
    f"--property=StandardOutput=truncate:{UNIT_LOG}", "--property=StandardError=inherit",
    "--setenv=DEBIAN_FRONTEND=noninteractive",
    "apt-get", "-y", "-o", "DPkg::Lock::Timeout=300",
    "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold", "upgrade",
]  # fmt: skip
UNIT_STOP = ["systemctl", "stop", UNIT]
UNIT_RESET = ["systemctl", "reset-failed", UNIT]
UNIT_SHOW = ["systemctl", "show", UNIT, "-p", "SubState", "-p", "Result", "-p", "ExecMainStatus"]
UNIT_TAIL = ["tail", "-n", "300", UNIT_LOG]
DOCKER_AT_BOOT = ["systemctl", "is-enabled", "docker"]
REBOOT = ["systemctl", "reboot"]
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")  # the kernel's: the same in a container
REBOOT_STATE = "host-reboot.json"
UPGRADE_STATE = "host-upgrade.json"
CHECK_EVERY_S = 6 * 3600
FIRST_CHECK_S = 60
UPDATE_TIMEOUT_S = 300
UPGRADE_TIMEOUT_S = 3600
POLL_S = 3.0
REBOOT_WAIT_S: float = 300  # still here after that: the host did not reboot

_INST = re.compile(r"^Inst (\S+) \[([^\]]+)\] \((\S+) ([^)]*)\)", re.M)
_KERNEL = re.compile(r"^(\d+(?:\.\d+)*)(?:-(\d+))?")


class HostUpdateError(ConflictError):
    code = "host_update_refused"


def parse_simulation(text: str) -> list[dict[str, Any]]:
    """The packages ``apt-get -s upgrade`` would upgrade: name, versions, security fix."""
    return [{"name": m[1], "current": m[2], "candidate": m[3],
             "security": "security" in m[4].lower()} for m in _INST.finditer(text)]  # fmt: skip


def kernel_key(release: str) -> tuple[int, ...]:
    """``6.1.0-26-amd64`` -> (6, 1, 0, 26); ``6.6.51+rpt-rpi-v8`` -> (6, 6, 51)."""
    m = _KERNEL.match(release.strip())
    if not m:
        return ()
    return (*map(int, m[1].split(".")), *([int(m[2])] if m[2] else []))


def newer_kernel(running: str, installed: str) -> bool:
    """A kernel installed after the running one (Debian sets no reboot flag for it)."""
    keys = [k for line in installed.split() if (k := kernel_key(line))]
    return bool(keys) and max(keys) > kernel_key(running)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(path)


class HostUpdates:
    def __init__(self, *, fw: HostFirewall, sessions: async_sessionmaker[AsyncSession],
                 jobs: JobQueue, zone_actions: ZoneActions, store: StateStore, bus: EventBus,
                 clock: Clock, data_dir: Path,
                 boot_id: Callable[[], str] | None = None) -> None:  # fmt: skip
        self.fw = fw
        self.sessions = sessions
        self.jobs = jobs
        self.zone_actions = zone_actions
        self.store = store
        self.bus = bus
        self.clock = clock
        self.data_dir = data_dir
        self.boot_id = boot_id or (lambda: BOOT_ID.read_text().strip())
        self.view: dict[str, Any] = {"checked_at": None, "packages": [], "reboot": False,
                                     "error": None}  # fmt: skip
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def register(self) -> None:
        self.jobs.register(JobKind.HOST_UPGRADE, self._upgrade)
        self.jobs.register(JobKind.HOST_REBOOT, self._reboot)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._every(), name="host-updates")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _every(self) -> None:
        await asyncio.sleep(FIRST_CHECK_S)
        while True:
            if await self.fw.agent_enabled():
                try:
                    await self.check()
                except Exception:
                    logger.exception("host package check failed")
            await asyncio.sleep(CHECK_EVERY_S)

    # --- check -------------------------------------------------------------------------
    async def check(self) -> dict[str, Any]:
        """Refresh the package lists, then what an upgrade would bring (one at a time)."""
        async with self._lock:
            try:
                code, out = await self.fw._run(APT_UPDATE, check=False, limit_s=UPDATE_TIMEOUT_S)
                if code != 0:
                    raise HostUpdateError("apt-get update failed", output=out[-500:],
                                          reason="apt")  # fmt: skip
                _, sim = await self.fw._run(SIMULATE, limit_s=UPDATE_TIMEOUT_S)
                self.view = {"checked_at": self.clock.now().isoformat(),
                             "packages": parse_simulation(sim),
                             "reboot": await self.reboot_required(), "error": None}  # fmt: skip
            except ConflictError as exc:
                self.view = {**self.view, "checked_at": self.clock.now().isoformat(),
                             "error": str(exc)}  # fmt: skip
                raise
        return self.view

    async def reboot_required(self) -> bool:
        code, _ = await self.fw._run(REBOOT_FLAG, check=False)
        if code == 0:
            return True
        _, running = await self.fw._run(RUNNING_KERNEL)
        code, installed = await self.fw._run(KERNELS, check=False)
        return code == 0 and newer_kernel(running, installed)

    # --- requests ---------------------------------------------------------------------
    async def _request(self, kind: JobKind) -> Job:
        if not await self.fw.agent_enabled():
            raise HostUpdateError("the host agent is off (Settings → host firewall)",
                                  reason="agent_off")  # fmt: skip
        async with self.sessions() as session, session.begin():
            busy = await session.scalar(select(Job.id).where(
                Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING))).limit(1))  # fmt: skip
            if busy is not None:
                raise HostUpdateError("wait for the running jobs to end", reason="jobs", job=busy)
            job = self.jobs.add(session, kind)
        self.jobs.wake()
        return job

    async def request_upgrade(self) -> Job:
        return await self._request(JobKind.HOST_UPGRADE)

    async def request_reboot(self) -> Job:
        return await self._request(JobKind.HOST_REBOOT)

    async def reboot_plan(self) -> dict[str, Any]:
        """What a reboot does: the apps Hivora stops then starts again, the other containers
        (stopped by Docker at shutdown, back by their own restart policy)."""
        async with self.sessions() as session:
            apps = await self._running_apps(session)
        managed = {a.slug for a in apps}
        others = sorted({c.name for c in self.store.containers()
                         if c.state.value == "running" and self.store.key_of(c) not in managed
                         and "io.hivora.self" not in c.labels})  # fmt: skip
        return {"apps": [{"id": a.id, "name": a.name, "slug": a.slug} for a in apps],
                "others": others}  # fmt: skip

    async def _running_apps(self, session: AsyncSession) -> list[Application]:
        rows = await session.scalars(select(Application).order_by(Application.name))
        return [a for a in rows
                if (a.current_revision_id is not None or a.origin is Origin.ADOPTED)
                and self.store.app(a.slug).status not in DOWN]  # fmt: skip

    # --- the upgrade job ------------------------------------------------------------------
    async def _upgrade(self, ctx: JobContext) -> None:
        state_file = self.data_dir / UPGRADE_STATE
        resumed = (read_json(state_file) or {}).get("job") == ctx.job_id
        if not resumed:
            await self.fw._run(UNIT_STOP, check=False)
            await self.fw._run(UNIT_RESET, check=False)
            await ctx.log(" ".join(UPGRADE))
            await self.fw._run(UPGRADE, limit_s=60)
            write_json(state_file, {"job": ctx.job_id})
        else:
            await ctx.log(f"Hivora restarted: following {UNIT} again")
        try:
            result = await self._follow(ctx)
        finally:
            state_file.unlink(missing_ok=True)
        _, out = await self.fw._run(UNIT_TAIL, check=False)
        await ctx.log(out[-8000:])
        if result != "ok":
            raise HostUpdateError(f"apt-get upgrade failed ({result})", reason="apt")
        await ctx.progress(95, "check")
        try:
            await self.check()
        except ConflictError:
            pass
        self.bus.publish("host.upgraded", packages=len(self.view["packages"]))

    async def _follow(self, ctx: JobContext) -> str:
        """``ok`` once the unit ended well, else its result."""
        loop = asyncio.get_running_loop()
        end = loop.time() + UPGRADE_TIMEOUT_S
        while True:
            _, out = await self.fw._run(UNIT_SHOW, check=False)
            props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
            if props.get("SubState") not in ("running", "start", ""):
                ok = props.get("Result") == "success" and props.get("ExecMainStatus") == "0"
                return "ok" if ok else f"{props.get('Result')}, exit {props.get('ExecMainStatus')}"
            if loop.time() >= end:
                return "still running after an hour"
            await ctx.progress(50, "apt-get upgrade")
            await asyncio.sleep(POLL_S)

    # --- the reboot job -------------------------------------------------------------------
    async def _reboot(self, ctx: JobContext) -> None:
        state_file = self.data_dir / REBOOT_STATE
        state = read_json(state_file)
        if state and state.get("job") == ctx.job_id:  # resumed: Hivora is back
            rebooted = state.get("boot_id") != self.boot_id()
            await ctx.log("the host rebooted" if rebooted else "the host did not reboot")
            await self._start_again(ctx, [int(i) for i in state.get("apps", [])])
            state_file.unlink(missing_ok=True)
            if not rebooted:
                raise HostUpdateError("the host did not reboot", reason="no_reboot")
            self.bus.publish("host.rebooted")
            return
        _, out = await self.fw._run(DOCKER_AT_BOOT, check=False)
        if out.strip() != "enabled":
            raise HostUpdateError("Docker does not start at boot (systemctl enable docker): "
                                  "Hivora would not come back", reason="docker_boot")  # fmt: skip
        async with self.sessions() as session:
            ids = [a.id for a in await self._running_apps(session)]
        await ctx.log(f"stopping {len(ids)} app(s) before the reboot")
        await ctx.progress(10, "stop")
        for problem in await self.zone_actions.apps_in_order(ctx, ids, "stop"):
            await ctx.log(f"  {problem} (Docker stops it at shutdown)")
        write_json(state_file, {"job": ctx.job_id, "boot_id": self.boot_id(), "apps": ids})
        await ctx.log("systemctl reboot")
        await ctx.progress(60, "reboot")
        await ctx.flush()
        try:
            await self.fw._run(REBOOT)
        except Exception:
            state_file.unlink(missing_ok=True)
            await self._start_again(ctx, ids)
            raise
        await asyncio.sleep(REBOOT_WAIT_S)  # Docker stops Hivora well before
        state_file.unlink(missing_ok=True)
        await self._start_again(ctx, ids)
        raise HostUpdateError("the host did not reboot", reason="no_reboot")

    async def _start_again(self, ctx: JobContext, ids: list[int]) -> None:
        await ctx.log(f"starting {len(ids)} app(s) again")
        await ctx.progress(80, "start")
        problems = await self.zone_actions.apps_in_order(ctx, ids, "start")
        if problems:
            raise HostUpdateError("; ".join(problems)[-500:], reason="start")
