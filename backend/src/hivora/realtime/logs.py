"""Live logs of an app: every container followed, lines batched to the WebSocket.

Containers come and go (restart, recreate, update): the list is re-read every
few seconds and each container is followed again from its last line. Secret
values of the app are masked. A burst is capped per batch so a chatty
container cannot flood the socket; the drop is reported.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from hivora.core.redact import Redactor
from hivora.docker_gateway import ContainerInfo, ContainerState
from hivora.runtime import Runtime
from hivora.state import app_key
from hivora.web.deps import Operator, RuntimeDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["logs"])

SERVICE_LABEL = "com.docker.compose.service"
FIRST_TAIL = 300  # lines shown per container when the stream opens
BATCH_S = 0.25
MAX_BATCH = 500  # lines per batch; beyond, dropped and counted
RESCAN_S = 2.0

Send = Callable[[dict[str, Any]], Awaitable[None]]


def split_timestamp(line: str) -> tuple[str | None, str]:
    """Docker's "2026-09-28T10:00:00.123456789Z text" -> (time, text)."""
    head, sep, rest = line.partition(" ")
    if sep and head[:4].isdigit() and "T" in head:
        return head, rest
    return None, line


def unix(ts: str) -> int:
    return int(datetime.fromisoformat(ts[:19] + "+00:00").timestamp())


def service_of(c: ContainerInfo) -> str:
    return c.labels.get(SERVICE_LABEL) or c.name


def app_containers(rt: Runtime, slug: str) -> list[ContainerInfo]:
    return [c for c in rt.state.store.containers() if app_key(c) == slug]


class LogStream:
    def __init__(self, rt: Runtime, sid: str, slug: str, secrets: list[str], send: Send) -> None:
        self.rt = rt
        self.sid = sid
        self.slug = slug
        self.redact = Redactor(secrets)
        self.send = send
        self.pending: list[dict[str, Any]] = []
        self.dropped = 0
        self.last: dict[str, str] = {}  # container id -> last timestamp sent
        self.followers: dict[str, asyncio.Task[None]] = {}
        self.task: asyncio.Task[None] | None = None

    def containers(self) -> list[ContainerInfo]:
        return app_containers(self.rt, self.slug)

    async def follow(self, c: ContainerInfo) -> None:
        running = c.state is ContainerState.RUNNING
        last = self.last.get(c.id)
        tail: int | str = "all" if last else FIRST_TAIL
        since = unix(last) if last else None
        service = service_of(c)
        async for raw in self.rt.gateway.logs(c.id, follow=running, tail=tail, since=since,
                                              timestamps=True):  # fmt: skip
            ts, text = split_timestamp(raw)
            if ts and last and ts <= last:
                continue  # `since` has a one-second resolution: skip what was sent
            if ts:
                self.last[c.id] = ts
            if len(self.pending) >= MAX_BATCH:
                self.dropped += 1
                continue
            self.pending.append({"s": service, "t": ts, "l": self.redact(text)})

    async def flush(self) -> None:
        if self.pending or self.dropped:
            batch, self.pending = self.pending, []
            dropped, self.dropped = self.dropped, 0
            await self.send({"channel": "logs", "id": self.sid, "type": "lines",
                             "lines": batch, "dropped": dropped})  # fmt: skip

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        next_scan = 0.0
        try:
            while True:
                if loop.time() >= next_scan:
                    self.scan()
                    next_scan = loop.time() + RESCAN_S
                await asyncio.sleep(BATCH_S)
                await self.flush()
        finally:
            for t in self.followers.values():
                t.cancel()

    def scan(self) -> None:
        """Follow new containers, and those that restarted since their stream ended."""
        for c in self.containers():
            task = self.followers.get(c.id)
            if task and not task.done():
                continue
            if task and c.state is not ContainerState.RUNNING:
                continue  # already read to its end, still stopped
            self.followers[c.id] = asyncio.create_task(self._safe_follow(c))

    async def _safe_follow(self, c: ContainerInfo) -> None:
        try:
            await self.follow(c)
        except Exception as exc:  # container removed meanwhile, Docker hiccup
            logger.debug("log stream ended", extra={"container": c.name, "error": str(exc)})

    def start(self) -> None:
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task


async def snapshot(rt: Runtime, slug: str, secrets: list[str], *, tail: int | str,
                   service: str | None = None) -> list[str]:  # fmt: skip
    """Past lines of every container (or one service), merged by time: the download."""
    redact = Redactor(secrets)
    lines: list[tuple[str, str]] = []
    for c in (c for c in app_containers(rt, slug) if service in (None, service_of(c))):
        name = service_of(c)
        async for raw in rt.gateway.logs(c.id, tail=tail, timestamps=True):
            ts, text = split_timestamp(raw)
            lines.append((ts or "", f"{ts or '-'} [{name}] {redact(text)}"))
    lines.sort(key=lambda x: x[0])
    return [text for _, text in lines]


# --- download route (mounted under /api/v1/apps) ----------------------------


@router.get("/{app_id}/logs")
async def download(
    app_id: int, _: Operator, rt: RuntimeDep, service: str | None = Query(None, max_length=63),
    tail: int = Query(10_000, ge=1, le=200_000),
) -> PlainTextResponse:  # fmt: skip
    """Logs of the app's containers as text (last ``tail`` lines each), secrets masked."""
    async with rt.sessions() as session:
        app = await rt.apps.get(session, app_id)
        secrets = list((await rt.apps.decrypt_secrets(session, app.id)).values())
    lines = await snapshot(rt, app.slug, secrets, tail=tail, service=service)
    rt.bus.publish("app.logs_downloaded", app=app.slug, service=service)
    stamp = rt.clock.now().strftime("%Y%m%d-%H%M")
    return PlainTextResponse("\n".join(lines) + "\n", headers={
        "Content-Disposition": f'attachment; filename="{app.slug}-{stamp}.log"',
        "Cache-Control": "no-store",
    })  # fmt: skip
