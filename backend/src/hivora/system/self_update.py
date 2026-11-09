"""The "Update" button (M13, exception of 02/11/2026 in CLAUDE.md): Hivora replaced by the
latest release of its channel, by a fixed sequence of steps.

1. The panel (job ``self_update``): checks the release, pulls its image and checks the
   digest the release published, writes ``<data>/self-update.json`` and starts
   ``hivora-updater`` from the CURRENT image (a known good one), then waits to be stopped.
2. The updater (``python -m hivora self-update``): stops Hivora and renames it
   ``<name>-previous``, backs the panel up, runs ``bootstrap`` in the new image, creates the
   new container with the old one's exact configuration (only the image changes), waits for
   "healthy", then removes the previous one. Otherwise: the new one goes, the database comes
   back from the backup, the previous one starts again.
3. Whichever Hivora starts next (new, or old after a roll back) reads the result in the
   state file and closes the job.
"""

import asyncio
import json
import os
import re
import tarfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora import __version__
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.jobs.models import Job, JobKind, JobStatus
from hivora.jobs.queue import JobContext, JobQueue
from hivora.system.panel_backup import backup_panel
from hivora.system.releases import ReleaseChecker, newer

IMAGE = "ghcr.io/hivora-suite/hivora-panel"
STATE = "self-update.json"
TAG = re.compile(r"^v\d+\.\d+\.\d+(?:-rc\.\d+)?$")
HEALTH_TIMEOUT = 180.0  # seconds, the installer's 120 plus the health check's interval
TAKEOVER = 900.0  # the panel waits this long to be stopped by the updater
FOLLOW_EVERY = 2.0


class SelfUpdateError(ConflictError):
    code = "self_update_refused"


class Docker(Protocol):
    """``docker_gateway.self_update.SelfDocker``: the only Docker calls of the update."""

    async def find_self(self) -> dict[str, Any] | None: ...
    async def inspect(self, name: str) -> dict[str, Any]: ...
    async def exists(self, name: str) -> bool: ...
    async def image(self, ref: str) -> dict[str, Any]: ...
    async def pull(self, ref: str) -> list[str]: ...
    async def stop(self, name: str, grace: int = 30) -> None: ...
    async def rename(self, name: str, new: str) -> None: ...
    async def start(self, name: str) -> None: ...
    async def remove(self, name: str) -> None: ...
    async def create(self, name: str, body: dict[str, Any]) -> None: ...
    async def connect(self, network: str, name: str, endpoint: dict[str, Any]) -> None: ...
    async def run(self, image: str, cmd: list[str], binds: list[str],
                  env: list[str]) -> tuple[int, str]: ...  # fmt: skip
    async def launch_updater(self, image: str, cmd: list[str], data_dir: str,
                             env: list[str]) -> None: ...  # fmt: skip
    async def wait_healthy(self, name: str, within: float, every: float = 2) -> str: ...
    async def close(self) -> None: ...


def user_env(container: dict[str, Any], image: dict[str, Any]) -> list[str]:
    """The container's own variables: its image's defaults left out (the new image's apply)."""
    defaults = set((image.get("Config") or {}).get("Env") or [])
    return [e for e in (container.get("Config") or {}).get("Env") or [] if e not in defaults]


def clone(old: dict[str, Any], old_image: dict[str, Any],
          image: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:  # fmt: skip
    """The new container: the old one's configuration with another image (create body, and
    the networks to join after the first). Image defaults (env, labels such as the OCI
    version) are left to the new image."""
    cfg, host = old.get("Config") or {}, old.get("HostConfig") or {}
    image_labels = (old_image.get("Config") or {}).get("Labels") or {}
    labels = {k: v for k, v in (cfg.get("Labels") or {}).items() if image_labels.get(k) != v}
    keep = ("Binds", "Mounts", "PortBindings", "RestartPolicy", "NetworkMode", "ExtraHosts",
            "LogConfig", "Dns", "CapAdd", "CapDrop", "SecurityOpt")  # fmt: skip
    host_config = {k: host[k] for k in keep if host.get(k)}
    body: dict[str, Any] = {"Image": image, "Env": user_env(old, old_image), "Labels": labels,
                            "HostConfig": host_config}  # fmt: skip
    if cfg.get("ExposedPorts"):
        body["ExposedPorts"] = cfg["ExposedPorts"]
    endpoints = {}
    for net, ep in ((old.get("NetworkSettings") or {}).get("Networks") or {}).items():
        endpoint: dict[str, Any] = {}
        if (ep or {}).get("IPAMConfig"):
            endpoint["IPAMConfig"] = ep["IPAMConfig"]
        aliases = [a for a in (ep or {}).get("Aliases") or [] if a != old.get("Id", "")[:12]]
        if aliases:
            endpoint["Aliases"] = aliases
        endpoints[net] = endpoint
    first = host_config.get("NetworkMode")
    if first in endpoints:
        body["NetworkingConfig"] = {"EndpointsConfig": {first: endpoints.pop(first)}}
    endpoints = {n: e for n, e in endpoints.items() if n not in ("bridge", "host", "none")}
    return body, endpoints


# --- the state file, shared by the panel and the updater ---------------------------------
def read_state(data_dir: Path) -> dict[str, Any] | None:
    try:
        return dict(json.loads((data_dir / STATE).read_text()))
    except (OSError, ValueError):
        return None


def write_state(data_dir: Path, state: dict[str, Any]) -> None:
    path = data_dir / STATE
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
    tmp.replace(path)


class SelfUpdate:
    """In the panel: the button's job, and closing it at the next start."""

    def __init__(self, *, settings: Settings, sessions: async_sessionmaker[AsyncSession],
                 jobs: JobQueue, releases: ReleaseChecker, bus: EventBus, clock: Clock,
                 docker: Callable[[], Docker | None]) -> None:  # fmt: skip
        self.settings = settings
        self.sessions = sessions
        self.jobs = jobs
        self.releases = releases
        self.bus = bus
        self.clock = clock
        self.docker = docker
        self._follow: asyncio.Task[None] | None = None

    def register(self) -> None:
        self.jobs.register(JobKind.SELF_UPDATE, self._handle)

    async def available(self) -> bool:
        """On, and this Hivora was started by its installer (its container is labelled)."""
        docker = self.docker() if self.settings.self_update else None
        try:
            return docker is not None and await docker.find_self() is not None
        except Exception:
            return False

    async def request(self, tag: str) -> Job:
        """The latest release of the channel, newer than this one, once nothing else runs."""
        if not self.settings.self_update:
            raise SelfUpdateError("the Update button is turned off (HIVORA_SELF_UPDATE)",
                                  reason="off")  # fmt: skip
        view = await self.releases.view()
        latest = view.get("latest") or {}
        if not TAG.match(tag) or latest.get("tag") != tag or not newer(__version__, tag):
            raise SelfUpdateError("only the latest, newer release can be installed",
                                  reason="not_latest")  # fmt: skip
        if not latest.get("digest"):
            raise SelfUpdateError("the release does not publish its image digest",
                                  reason="no_digest")  # fmt: skip
        if read_state(self.settings.data_dir):
            raise SelfUpdateError("an update is already under way", reason="busy")
        if not await self.available():
            raise SelfUpdateError("Hivora was not started by its installer: run the script",
                                  reason="no_container")  # fmt: skip
        async with self.sessions() as session, session.begin():
            busy = await session.scalar(select(Job.id).where(
                Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING))
            ).limit(1))  # fmt: skip
            if busy is not None:
                raise SelfUpdateError("wait for the running jobs to end", reason="jobs", job=busy)
            job = self.jobs.add(session, JobKind.SELF_UPDATE,
                                params={"tag": tag, "digest": latest["digest"]})  # fmt: skip
        self.jobs.wake()
        return job

    async def _handle(self, ctx: JobContext) -> None:
        tag, digest = str(ctx.params["tag"]), str(ctx.params["digest"])
        docker = self.docker()
        me = await docker.find_self() if docker else None
        if docker is None or me is None:
            raise SelfUpdateError("Hivora was not started by its installer: run the script",
                                  reason="no_container")  # fmt: skip
        ref = f"{IMAGE}:{tag}"
        await ctx.log(f"docker pull {ref}")
        digests = await docker.pull(ref)
        if f"{IMAGE}@{digest}" not in digests:
            raise SelfUpdateError(f"the image digest is not the release's ({digest})",
                                  reason="digest")  # fmt: skip
        await ctx.log(f"digest {digest}: the release's")
        name = str(me.get("Name") or "hivora").lstrip("/")
        write_state(self.settings.data_dir, {
            "job": ctx.job_id, "from": __version__, "tag": tag, "image": f"{IMAGE}@{digest}",
            "container": name, "status": "running", "error": None, "log": [],
        })  # fmt: skip
        env = [f"{k}={v}" for k, v in os.environ.items() if k.startswith("HIVORA_")]
        await ctx.log(f"Hivora {__version__} hands over to hivora-updater (restart)")
        await ctx.flush()
        try:
            await docker.launch_updater(str(me["Image"]), ["python", "-m", "hivora", "self-update"],
                                        str(self.settings.data_dir), env)  # fmt: skip
        except Exception:
            (self.settings.data_dir / STATE).unlink(missing_ok=True)
            raise
        await asyncio.sleep(TAKEOVER)  # stopped by the updater well before
        raise SelfUpdateError("the updater did not stop Hivora", reason="no_takeover")

    # --- at the next start --------------------------------------------------------------
    async def settle(self) -> None:
        """Before the job queue starts: close the job with the updater's result, or leave it
        running while the updater still waits for this Hivora to be healthy."""
        state = read_state(self.settings.data_dir)
        if state is None or not isinstance(state.get("job"), int):
            return
        if state.get("status") == "running":
            self.jobs.keep(state["job"])
            self._follow = asyncio.create_task(self._wait_result(), name="self-update")
            return
        await self._close(state)

    async def _wait_result(self) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + TAKEOVER
        while loop.time() < end:
            await asyncio.sleep(FOLLOW_EVERY)
            state = read_state(self.settings.data_dir)
            if state is None:
                return
            if state.get("status") != "running":
                await self._close(state)
                return
        state = read_state(self.settings.data_dir) or {}
        await self._close({**state, "status": "failed", "error": "no report from the updater"})

    async def _close(self, state: dict[str, Any]) -> None:
        ok = state.get("status") == "succeeded"
        status = JobStatus.SUCCEEDED if ok else JobStatus.FAILED
        error = None if ok else str(state.get("error") or "the update failed")
        lines = "".join(f"{line}\n" for line in state.get("log") or [])
        async with self.sessions() as session, session.begin():
            job = await session.get(Job, state["job"])
            if job is not None and job.status is JobStatus.RUNNING:
                await session.execute(update(Job).where(Job.id == job.id).values(
                    status=status, error=error, finished_at=self.clock.now(),
                    log=job.log + lines, progress=100,
                ))  # fmt: skip
        (self.settings.data_dir / STATE).unlink(missing_ok=True)
        self.bus.publish("job.finished", id=state["job"], status=status.value, error=error,
                         app=None)  # fmt: skip

    async def stop(self) -> None:
        if self._follow:
            self._follow.cancel()


# --- the updater (python -m hivora self-update, in hivora-updater) ------------------------
def restore_database(archive: Path, data_dir: Path) -> None:
    """The panel's database back from its backup (the WAL files belong to the other one)."""
    for suffix in ("-wal", "-shm"):
        (data_dir / f"hivora.db{suffix}").unlink(missing_ok=True)
    with tarfile.open(archive) as tar:
        member = tar.getmember("hivora.db")
        source = tar.extractfile(member)
        if source is None:
            raise FileNotFoundError("no hivora.db in the backup")
        tmp = data_dir / "hivora.db.restore"
        tmp.write_bytes(source.read())
        tmp.replace(data_dir / "hivora.db")


async def run_updater(settings: Settings, docker: Docker) -> dict[str, Any]:
    """The fixed steps; the state file says how it ended."""
    data = settings.data_dir
    state = read_state(data)
    if state is None or state.get("status") != "running":
        raise FileNotFoundError(f"no update to run in {data / STATE}")
    log: list[str] = state["log"]

    def say(line: str) -> None:
        log.append(f"{datetime.now(UTC):%H:%M:%S} {line}")
        write_state(data, state)

    def end(status: str, error: str | None = None) -> dict[str, Any]:
        state.update(status=status, error=error)
        say(f"{status}" + (f": {error}" if error else ""))
        return state

    name, image = str(state["container"]), str(state["image"])
    previous = f"{name}-previous"
    try:
        old = await docker.inspect(name)
        old_image = await docker.image(str(old["Image"]))
    except Exception as exc:
        return end("failed", f"Hivora's container cannot be read: {exc}")
    stopped = created = backup = None
    try:
        say(f"docker stop {name}; docker rename {name} {previous}")
        await docker.stop(name)
        stopped = True
        await docker.rename(name, previous)
        backup = backup_panel(data)
        say(f"backup: {backup}")
        binds = [b for b in (old.get("HostConfig") or {}).get("Binds") or []
                 if not b.startswith("/var/run/docker.sock:")]  # fmt: skip
        say(f"python -m hivora bootstrap ({image})")
        code, out = await docker.run(image, ["python", "-m", "hivora", "bootstrap"], binds,
                                     user_env(old, old_image))  # fmt: skip
        if code != 0:
            raise RuntimeError(f"bootstrap failed ({code}): {out.strip()[-500:]}")
        body, others = clone(old, old_image, image)
        say(f"docker create {name} ({image}, the same options)")
        await docker.create(name, body)
        created = True
        for network, endpoint in others.items():
            await docker.connect(network, name, endpoint)
        await docker.start(name)
        say("waiting for healthy")
        health = await docker.wait_healthy(name, HEALTH_TIMEOUT)
        if health != "healthy":
            raise RuntimeError(f"the new version is not healthy ({health})")
        await docker.remove(previous)
        return end("succeeded")
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        say(f"error: {error}; rolling back")
        try:
            if created:
                await docker.remove(name)
            if backup is not None:  # bootstrap may have migrated it
                restore_database(backup, data)
                say("database restored from the backup")
            if stopped:
                if await docker.exists(previous):
                    await docker.rename(previous, name)
                state.update(status="rolled_back", error=error)
                say(f"docker start {name} (Hivora {state.get('from')})")
                write_state(data, state)
                await docker.start(name)
                return state
        except Exception as again:
            return end("failed", f"{error}; the roll back failed too: {again}")
        return end("failed", error)
