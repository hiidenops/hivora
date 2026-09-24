"""The single multiplexed WebSocket (/ws).

Client -> server:  {"op": "subscribe" | "unsubscribe", "channel": "state" | "jobs" | "metrics"}
                   {"op": "subscribe" | "unsubscribe", "channel": "job", "id": <job id>}
Server -> client:  {"channel": "state", "type": "snapshot", "apps": {slug: status}}
                   {"channel": "state", "type": "app", "app": slug, "status": ...}
                   {"channel": "jobs", "type": "started" | "progress" | "finished", ...}
                   {"channel": "job", "id": n, "type": "log", "line": ...}
                   {"channel": "metrics", "type": "host", ...sample}

Authenticated by the session cookie; the Origin must match the Host
(cross-site WebSocket hijacking). Log and console channels come later.
"""

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hivora.core.events import Event
from hivora.runtime import Runtime
from hivora.web.deps import SESSION_COOKIE

logger = logging.getLogger(__name__)
router = APIRouter()

REVALIDATE_EVERY_S = 60.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403


def same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    return origin is None or urlsplit(origin).netloc == ws.headers.get("host")


class Connection:
    def __init__(self, ws: WebSocket, runtime: Runtime) -> None:
        self.ws = ws
        self.rt = runtime
        self.channels: set[str] = set()
        self.jobs: set[int] = set()

    async def send(self, message: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(message, default=str))

    async def handle_client(self) -> None:
        while True:
            try:
                msg = json.loads(await self.ws.receive_text())
                op, channel = msg["op"], msg["channel"]
            except (ValueError, KeyError, TypeError):
                await self.send({"type": "error", "code": "bad_message"})
                continue
            subscribe = op == "subscribe"
            if channel == "job" and isinstance(msg.get("id"), int):
                (self.jobs.add if subscribe else self.jobs.discard)(msg["id"])
            elif channel in ("state", "jobs", "metrics"):
                (self.channels.add if subscribe else self.channels.discard)(channel)
                if subscribe and channel == "state":
                    apps = {k: a.status.value for k, a in self.rt.state.store.apps().items()}
                    await self.send({"channel": "state", "type": "snapshot", "apps": apps})
            else:
                await self.send({"type": "error", "code": "unknown_channel"})

    async def forward(self, event: Event) -> None:
        p = event.payload
        if event.topic == "state.app.changed" and "state" in self.channels:
            await self.send(
                {"channel": "state", "type": "app", "app": p["app"], "status": p["status"]}
            )
        elif event.topic.startswith("job.") and event.topic != "job.log":
            if "jobs" in self.channels:
                await self.send({"channel": "jobs", "type": event.topic[4:], **p})
        elif event.topic == "metrics.host" and "metrics" in self.channels:
            await self.send({"channel": "metrics", "type": "host", **p})
        elif event.topic == "job.log" and p.get("id") in self.jobs:
            await self.send({"channel": "job", "id": p["id"], "type": "log", "line": p["line"]})

    async def pump_events(self, token: str) -> None:
        loop = asyncio.get_running_loop()
        next_check = loop.time() + REVALIDATE_EVERY_S
        async with self.rt.bus.subscribe("*", maxsize=2000) as sub:
            while True:
                try:
                    async with asyncio.timeout(max(0.0, next_check - loop.time())):
                        await self.forward(await sub.queue.get())
                except TimeoutError:
                    # Revoked sessions and disabled users lose their live feed too.
                    if await self.rt.auth.authenticate(token) is None:
                        await self.ws.close(CLOSE_UNAUTHORIZED)
                        return
                    next_check = loop.time() + REVALIDATE_EVERY_S


@router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    runtime: Runtime = ws.app.state.runtime
    token = ws.cookies.get(SESSION_COOKIE)
    found = await runtime.auth.authenticate(token) if token else None
    if not same_origin(ws) or found is None or token is None:
        await ws.close(CLOSE_UNAUTHORIZED)
        return
    user, _ = found
    if user.must_change_password:
        await ws.close(CLOSE_FORBIDDEN)
        return
    await ws.accept()
    conn = Connection(ws, runtime)
    tasks = [
        asyncio.create_task(conn.handle_client()),
        asyncio.create_task(conn.pump_events(token)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await task
