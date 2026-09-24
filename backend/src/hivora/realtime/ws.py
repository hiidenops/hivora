"""The single multiplexed WebSocket (/ws).

Client -> server:  {"op": "subscribe" | "unsubscribe", "channel": "state" | "jobs" | "metrics"}
                   {"op": "subscribe" | "unsubscribe", "channel": "job", "id": <job id>}
                   {"op": "subscribe" | "unsubscribe", "channel": "app_metrics", "app": slug}
                   {"op": "console.open", "id": cid, "app": app_id, "kind": "server" | "shell",
                    "rows": n, "cols": n, "totp_code"?: "123456"}
                   {"op": "console.input", "id": cid, "data": "..."}
                   {"op": "console.resize", "id": cid, "rows": n, "cols": n}
                   {"op": "console.close", "id": cid}
Server -> client:  {"channel": "state", "type": "snapshot", "apps": {slug: status}}
                   {"channel": "state", "type": "app", "app": slug, "status": ...}
                   {"channel": "jobs", "type": "started" | "progress" | "finished", ...}
                   {"channel": "job", "id": n, "type": "log", "line": ...}
                   {"channel": "metrics", "type": "host", ...sample}
                   {"channel": "app_metrics", "app": slug, "type": "snapshot" | "sample", ...}
                   {"channel": "console", "id": cid,
                    "type": "opened" | "data" | "closed" | "error", ...}

Authenticated by the session cookie; the Origin must match the Host
(cross-site WebSocket hijacking).
"""

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hivora.auth.models import Role, User
from hivora.core.context import Actor, current_actor
from hivora.core.errors import HivoraError
from hivora.core.events import Event
from hivora.realtime.console import Console
from hivora.runtime import Runtime
from hivora.web.deps import SESSION_COOKIE

logger = logging.getLogger(__name__)
router = APIRouter()

REVALIDATE_EVERY_S = 60.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
MAX_INPUT = 4096


def same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    return origin is None or urlsplit(origin).netloc == ws.headers.get("host")


class Connection:
    def __init__(self, ws: WebSocket, runtime: Runtime, user: User, session_id: int) -> None:
        self.ws = ws
        self.rt = runtime
        self.user = user
        self.session_id = session_id
        self.channels: set[str] = set()
        self.jobs: set[int] = set()
        self.app_metrics: set[str] = set()  # slugs this tab watches
        self.consoles: dict[str, Console] = {}
        self._send_lock = asyncio.Lock()  # several tasks write to one socket

    async def send(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.ws.send_text(json.dumps(message, default=str))

    async def handle_client(self) -> None:
        while True:
            try:
                msg = json.loads(await self.ws.receive_text())
                op = msg["op"]
                if op.startswith("console."):
                    await self.handle_console(op, msg)
                    continue
                channel = msg["channel"]
            except (ValueError, KeyError, TypeError, AttributeError):
                await self.send({"type": "error", "code": "bad_message"})
                continue
            subscribe = op == "subscribe"
            if channel == "app_metrics" and isinstance(msg.get("app"), str):
                await self.watch_app(msg["app"][:63], subscribe)
            elif channel == "job" and isinstance(msg.get("id"), int):
                (self.jobs.add if subscribe else self.jobs.discard)(msg["id"])
            elif channel in ("state", "jobs", "metrics"):
                (self.channels.add if subscribe else self.channels.discard)(channel)
                if subscribe and channel == "state":
                    apps = {k: a.status.value for k, a in self.rt.state.store.apps().items()}
                    await self.send({"channel": "state", "type": "snapshot", "apps": apps})
            else:
                await self.send({"type": "error", "code": "unknown_channel"})

    async def handle_console(self, op: str, msg: dict[str, Any]) -> None:
        cid = str(msg["id"])[:64]
        console = self.consoles.get(cid)
        if op == "console.open" and console is None:
            await self.open_console(cid, msg)
        elif op == "console.input" and console:
            await console.write(str(msg["data"])[:MAX_INPUT])
        elif op == "console.resize" and console:
            await console.session.resize(int(msg["rows"]), int(msg["cols"]))
        elif op == "console.close" and console:
            await self.close_console(cid)

    async def open_console(self, cid: str, msg: dict[str, Any]) -> None:
        def error(code: str) -> dict[str, Any]:
            return {"channel": "console", "id": cid, "type": "error", "code": code}

        if not self.user.role.allows(Role.OPERATOR):
            await self.send(error("insufficient_role"))
            return
        # Audit entries of this connection carry the user (the WS has no request).
        current_actor.set(
            Actor(self.user.id, self.user.username, self.ws.client.host if self.ws.client else None)
        )
        auth = self.rt.auth
        try:
            if not auth.console_confirmed(self.user, self.session_id):
                if not msg.get("totp_code"):
                    await self.send(error("totp_required"))
                    return
                await auth.confirm_console(self.user.id, self.session_id, str(msg["totp_code"]))
            console = await self.rt.consoles.open(
                cid, int(msg["app"]), str(msg.get("kind", "shell")),
                int(msg.get("rows", 24)), int(msg.get("cols", 80)), self.send,
            )  # fmt: skip
        except HivoraError as exc:
            await self.send({**error(exc.code), "message": str(exc)})
            return
        self.consoles[cid] = console
        await self.send(
            {"channel": "console", "id": cid, "type": "opened", "service": console.target.service}
        )

        async def run() -> None:
            await console.pump()
            self.consoles.pop(cid, None)
            await self.rt.consoles.close(console)

        console.task = asyncio.create_task(run())

    async def close_console(self, cid: str) -> None:
        console = self.consoles.pop(cid, None)
        if console:
            await self.rt.consoles.close(console)

    async def watch_app(self, slug: str, on: bool) -> None:
        if on and slug not in self.app_metrics:
            self.app_metrics.add(slug)
            history = self.rt.app_metrics.watch(slug)
            await self.send({"channel": "app_metrics", "app": slug, "type": "snapshot",
                             "samples": history})  # fmt: skip
        elif not on and slug in self.app_metrics:
            self.app_metrics.discard(slug)
            self.rt.app_metrics.unwatch(slug)

    async def close_all(self) -> None:
        for cid in list(self.consoles):
            await self.close_console(cid)
        for slug in list(self.app_metrics):
            await self.watch_app(slug, False)

    async def forward(self, event: Event) -> None:
        p = event.payload
        if event.topic == "state.app.changed" and "state" in self.channels:
            await self.send(
                {"channel": "state", "type": "app", "app": p["app"], "status": p["status"]}
            )
        elif event.topic.startswith("job.") and event.topic != "job.log":
            if "jobs" in self.channels:
                await self.send({"channel": "jobs", "type": event.topic[4:], **p})
        elif event.topic == "metrics.app" and p.get("app") in self.app_metrics:
            await self.send({"channel": "app_metrics", "type": "sample", **p})
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
    user, session = found
    if user.must_change_password:
        await ws.close(CLOSE_FORBIDDEN)
        return
    await ws.accept()
    conn = Connection(ws, runtime, user, session.id)
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
        await conn.close_all()
