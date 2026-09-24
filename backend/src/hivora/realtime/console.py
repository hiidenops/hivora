"""Interactive consoles in app containers, carried by the WebSocket "console" channel.

Two kinds: "server" (the template's game console, e.g. rcon-cli) and "shell"
(sh/bash). Never a shell on the host. Opening and closing are audited, never
the keystrokes; at most 8 consoles at once, closed after 30 min without input.
"""

import asyncio
import codecs
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from hivora.core.errors import ConflictError, HivoraError
from hivora.docker_gateway import ExecSession
from hivora.runtime import Runtime

logger = logging.getLogger(__name__)

MAX_CONSOLES = 8
IDLE_TIMEOUT_S = 30 * 60
SHELL = ["sh", "-c", "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi"]
LABEL_SERVICE = "com.docker.compose.service"

Send = Callable[[dict[str, Any]], Awaitable[None]]


class ConsoleUnavailableError(HivoraError):
    code = "console_unavailable"


class TooManyConsolesError(ConflictError):
    code = "too_many_consoles"


@dataclass
class Target:
    container_id: str
    service: str
    cmd: list[str]
    slug: str


async def resolve(rt: Runtime, app_id: int, kind: str) -> Target:
    """The main service's running container and the command to run in it."""
    async with rt.sessions() as session:
        app, entry, container = await rt.apps.main_container(session, app_id)
    template = entry.template if entry else None
    if kind == "server":
        cmd = template.game.console if template and template.game else None
        if not cmd:
            raise ConsoleUnavailableError("this app has no server console")
    elif kind == "shell":
        cmd = SHELL
    else:
        raise ConsoleUnavailableError("unknown console kind")
    if container is None:
        raise ConsoleUnavailableError("the app is not running")
    return Target(container.id, container.labels.get(LABEL_SERVICE, container.name), cmd, app.slug)


class Console:
    def __init__(
        self, cid: str, session: ExecSession, target: Target, kind: str, send: Send
    ) -> None:
        self.cid = cid
        self.session = session
        self.target = target
        self.kind = kind
        self.send = send
        self.opened = time.monotonic()
        self.last_input = self.opened
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.task: asyncio.Task[None] | None = None

    async def pump(self) -> None:
        """Container output -> browser, until exit or idle timeout."""
        while True:
            idle_left = IDLE_TIMEOUT_S - (time.monotonic() - self.last_input)
            if idle_left <= 0:
                await self.send(
                    {"channel": "console", "id": self.cid, "type": "closed", "reason": "idle"}
                )
                return
            try:
                async with asyncio.timeout(idle_left):
                    chunk = await self.session.read()
            except TimeoutError:
                continue
            if chunk is None:
                await self.send(
                    {"channel": "console", "id": self.cid, "type": "closed", "reason": "exited"}
                )
                return
            text = self._decoder.decode(chunk)
            if text:
                await self.send(
                    {"channel": "console", "id": self.cid, "type": "data", "data": text}
                )

    async def write(self, data: str) -> None:
        self.last_input = time.monotonic()
        await self.session.write(data.encode())


class ConsoleManager:
    """Global limit across every connection: consoles cost memory."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.open_count = 0

    async def open(
        self, cid: str, app_id: int, kind: str, rows: int, cols: int, send: Send
    ) -> Console:
        if self.open_count >= MAX_CONSOLES:
            raise TooManyConsolesError("too many consoles open", max=MAX_CONSOLES)
        target = await resolve(self.rt, app_id, kind)
        session = await self.rt.gateway.open_exec(target.container_id, target.cmd)
        with suppress(Exception):
            await session.resize(rows, cols)
        self.open_count += 1
        console = Console(cid, session, target, kind, send)
        self.rt.bus.publish("console.opened", app=target.slug, kind=kind, service=target.service)
        return console

    async def close(self, console: Console) -> None:
        # Called from the console's own task when it ends by itself: never await itself.
        if console.task and console.task is not asyncio.current_task():
            console.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await console.task
        with suppress(Exception):
            await console.session.close()
        self.open_count -= 1
        self.rt.bus.publish(
            "console.closed",
            app=console.target.slug,
            kind=console.kind,
            seconds=round(time.monotonic() - console.opened),
        )
