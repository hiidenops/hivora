"""Writes compose files and drives the ``docker compose`` CLI.

The compose project name is the app slug, which is also the directory name,
so ``cd /opt/hivora/data/apps/<slug> && docker compose up -d`` works
without Hivora.
"""

import asyncio
import json
import logging
import os
import re
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hivora.compose_runner.progress import ProgressEvent, ProgressStatus, parse_progress_line
from hivora.core.errors import ConflictError, HivoraError, ValidationError
from hivora.core.redact import Redactor

logger = logging.getLogger(__name__)

COMPOSE_FILE = "compose.yaml"
ENV_FILE = ".env"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]


class ComposeError(HivoraError):
    code = "compose_failed"


class AppBusyError(ConflictError):
    code = "app_busy"


@dataclass(frozen=True, slots=True)
class ComposeResult:
    returncode: int
    events: tuple[ProgressEvent, ...]
    stdout: str

    @property
    def error(self) -> str | None:
        messages = [e.details or e.text for e in self.events if e.status is ProgressStatus.ERROR]
        return messages[-1] if messages else None


def _atomic_write(path: Path, content: str, *, mode: int) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, mode)  # O_CREAT mode is filtered by umask
    os.replace(tmp, path)


def validate_slug(slug: str) -> str:
    if not _SLUG.match(slug):
        raise ValidationError("invalid app slug", slug=slug)
    return slug


class ComposeRunner:
    def __init__(
        self,
        apps_dir: Path,
        *,
        compose_cmd: Sequence[str] = ("docker", "compose"),
        env: dict[str, str] | None = None,
    ) -> None:
        self.apps_dir = apps_dir
        self._cmd = tuple(compose_cmd)
        self._env = {**os.environ, **(env or {})}
        self._locks: dict[str, asyncio.Lock] = {}

    # --- files ------------------------------------------------------------
    def project_dir(self, slug: str) -> Path:
        return self.apps_dir / validate_slug(slug)

    def compose_path(self, slug: str) -> Path:
        return self.project_dir(slug) / COMPOSE_FILE

    def write(self, slug: str, compose_yaml: str, env: dict[str, str] | None = None) -> Path:
        """Atomically replace the app's compose file and, if given, its ``.env``.

        ``.env`` holds secret values (mode 0600); Compose reads it for
        interpolation, so the stack also works without Hivora.
        """
        path = self.compose_path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        if env is not None:
            lines = []
            for key, value in sorted(env.items()):
                if "'" in value or "\n" in value:
                    raise ValidationError("unsupported character in secret", key=key)
                lines.append(f"{key}='{value}'\n")
            _atomic_write(path.parent / ENV_FILE, "".join(lines), mode=0o600)
        _atomic_write(path, compose_yaml, mode=0o644)
        return path

    # --- locking ----------------------------------------------------------
    @asynccontextmanager
    async def lock(self, slug: str) -> AsyncIterator[None]:
        """Exclusive access to one app's stack; fails fast instead of queueing."""
        lock = self._locks.setdefault(validate_slug(slug), asyncio.Lock())
        if lock.locked():
            raise AppBusyError("another operation is running on this app", slug=slug)
        async with lock:
            yield

    def is_locked(self, slug: str) -> bool:
        lock = self._locks.get(slug)
        return lock is not None and lock.locked()

    # --- commands ---------------------------------------------------------
    async def config(self, slug: str, *, redact: Iterable[str] = ()) -> dict[str, Any]:
        """Validated, fully resolved model of the compose file."""
        result = await self._run(slug, ["config", "--format", "json"], Redactor(redact))
        if result.returncode != 0:
            raise ComposeError(result.error or "invalid compose file", slug=slug)
        parsed: dict[str, Any] = json.loads(result.stdout)
        return parsed

    async def project(self, project: str, verb: str, *,
                      on_progress: ProgressCallback | None = None) -> ComposeResult:  # fmt: skip
        """start / stop / restart a stack by its project name, without its file.

        Adopted stacks: their compose file stays where the user keeps it (often
        out of Hivora's reach); Compose finds the containers by project label.
        """
        if verb not in ("start", "stop", "restart"):
            raise ValidationError("unsupported project command", verb=verb)
        argv = [*self._cmd, "--progress", "json", "--project-name", validate_slug(project), verb]
        self.apps_dir.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=self.apps_dir, env=self._env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        stdout, stderr = await proc.communicate()
        events = tuple(e for line in stderr.decode(errors="replace").splitlines()
                       if (e := parse_progress_line(line)) is not None)  # fmt: skip
        if on_progress:
            for e in events:
                await on_progress(e)
        result = ComposeResult(await proc.wait(), events, stdout.decode(errors="replace"))
        if result.returncode != 0:
            raise ComposeError(result.error or f"compose {verb} failed", slug=project)
        return result

    async def check(self, slug: str, compose_yaml: str, env: dict[str, str]) -> dict[str, Any]:
        """``docker compose config`` of a candidate file, without touching the app's own."""
        tmp = self.apps_dir / f".check-{validate_slug(slug)}"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            lines = "".join(f"{k}='{v}'\n" for k, v in sorted(env.items()))
            _atomic_write(tmp / ENV_FILE, lines, mode=0o600)
            _atomic_write(tmp / COMPOSE_FILE, compose_yaml, mode=0o600)
            result = await self._run(slug, ["config", "--format", "json"], Redactor(env.values()),
                                     project_dir=tmp)  # fmt: skip
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if result.returncode != 0:
            raise ComposeError(result.error or "invalid compose file", slug=slug)
        parsed: dict[str, Any] = json.loads(result.stdout)
        return parsed

    async def up(
        self,
        slug: str,
        *,
        on_progress: ProgressCallback | None = None,
        redact: Iterable[str] = (),
        wait: bool = True,
    ) -> ComposeResult:
        """``wait`` blocks until services are running/healthy (fails if one exits)."""
        args = ["up", "--detach", "--remove-orphans"] + (["--wait"] if wait else [])
        return await self._checked(slug, args, on_progress, redact)

    async def pull(
        self,
        slug: str,
        *,
        on_progress: ProgressCallback | None = None,
        redact: Iterable[str] = (),
    ) -> ComposeResult:
        return await self._checked(slug, ["pull"], on_progress, redact)

    async def stop(
        self, slug: str, *, on_progress: ProgressCallback | None = None
    ) -> ComposeResult:
        return await self._checked(slug, ["stop"], on_progress, ())

    async def start(
        self, slug: str, *, on_progress: ProgressCallback | None = None
    ) -> ComposeResult:
        return await self._checked(slug, ["start", "--wait"], on_progress, ())

    async def restart(
        self, slug: str, *, on_progress: ProgressCallback | None = None
    ) -> ComposeResult:
        return await self._checked(slug, ["restart"], on_progress, ())

    async def down(
        self,
        slug: str,
        *,
        remove_volumes: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> ComposeResult:
        args = ["down", "--remove-orphans"] + (["--volumes"] if remove_volumes else [])
        return await self._checked(slug, args, on_progress, ())

    async def logs(self, slug: str, *, tail: int = 40, redact: Iterable[str] = ()) -> list[str]:
        """Last lines of every service, to explain a failure (best effort)."""
        result = await self._run(
            slug, ["logs", "--no-color", "--tail", str(tail)], Redactor(redact)
        )
        return result.stdout.splitlines()

    async def _checked(
        self,
        slug: str,
        args: list[str],
        on_progress: ProgressCallback | None,
        redact: Iterable[str],
    ) -> ComposeResult:
        result = await self._run(slug, args, Redactor(redact), on_progress)
        if result.returncode != 0:
            raise ComposeError(result.error or f"docker compose {args[0]} failed", slug=slug)
        return result

    async def _run(
        self,
        slug: str,
        args: list[str],
        redactor: Redactor,
        on_progress: ProgressCallback | None = None,
        project_dir: Path | None = None,
    ) -> ComposeResult:
        project_dir = project_dir or self.project_dir(slug)
        argv = [
            *self._cmd,
            "--progress",
            "json",
            "--project-name",
            slug,
            "--file",
            str(project_dir / COMPOSE_FILE),
            *args,
        ]
        logger.info("compose", extra={"app": slug, "argv": argv[len(self._cmd) :]})
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=project_dir,
            env=self._env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout and proc.stderr
        events: list[ProgressEvent] = []

        async def read_progress(stream: asyncio.StreamReader) -> None:
            async for raw in stream:
                event = parse_progress_line(redactor(raw.decode(errors="replace")))
                if event is None:
                    continue
                events.append(event)
                if on_progress:
                    await on_progress(event)

        stdout, _ = await asyncio.gather(proc.stdout.read(), read_progress(proc.stderr))
        returncode = await proc.wait()
        return ComposeResult(returncode, tuple(events), redactor(stdout.decode(errors="replace")))
