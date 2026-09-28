"""In-memory DockerGateway for tests and UI development without Docker."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import replace
from datetime import datetime

from hivora.docker_gateway.base import ContainerNotFoundError, DockerGateway, ExecSession
from hivora.docker_gateway.models import (
    ContainerInfo,
    DockerEvent,
    NetworkInfo,
    StatsSample,
)


class FakeExecSession(ExecSession):
    """Echoes input back, prefixed with the command, like a tiny REPL."""

    def __init__(self, cmd: list[str]) -> None:
        self.cmd = cmd
        self.size: tuple[int, int] | None = None
        self._out: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._out.put_nowait(f"$ {' '.join(cmd)}\r\n".encode())

    async def read(self) -> bytes | None:
        return await self._out.get()

    async def write(self, data: bytes) -> None:
        self._out.put_nowait(data)

    async def resize(self, rows: int, cols: int) -> None:
        self.size = (rows, cols)

    async def close(self) -> None:
        self._out.put_nowait(None)


class FakeDockerGateway(DockerGateway):
    def __init__(self) -> None:
        self.containers: dict[str, ContainerInfo] = {}
        self.networks: list[NetworkInfo] = []
        self.logs_by_container: dict[str, list[str]] = {}
        self.execs: list[FakeExecSession] = []
        # exec_run answers: command (joined by spaces) -> (exit code, output)
        self.exec_results: dict[str, tuple[int, str]] = {}
        self.exec_calls: list[list[str]] = []
        self.stats: dict[str, StatsSample] = {}  # stats_once answers, zeros by default
        self.arch = "x86_64"
        self.platforms: dict[str, list[str]] = {}  # image ref -> architectures (unknown if absent)
        self._subscribers: list[asyncio.Queue[DockerEvent | None]] = []

    # --- test helpers -----------------------------------------------------
    def put(self, container: ContainerInfo, action: str | None = None) -> None:
        """Add or replace a container, optionally emitting an event for it."""
        self.containers[container.id] = container
        if action:
            self.emit(DockerEvent("container", action, container.id, dict(container.labels)))

    def update(self, container_id: str, action: str, **changes: object) -> None:
        self.put(replace(self.containers[container_id], **changes), action)  # type: ignore[arg-type]

    def remove(self, container_id: str) -> None:
        container = self.containers.pop(container_id)
        self.emit(DockerEvent("container", "destroy", container_id, dict(container.labels)))

    def emit(self, event: DockerEvent) -> None:
        for queue in self._subscribers:
            queue.put_nowait(event)

    def disconnect(self) -> None:
        """Simulate the events stream dropping."""
        for queue in self._subscribers:
            queue.put_nowait(None)

    # --- DockerGateway ----------------------------------------------------
    async def ping(self) -> str:
        return "fake"

    async def ensure_network(self, name: str, labels: dict[str, str]) -> bool:
        if any(n.name == name for n in self.networks):
            return False
        self.networks.append(
            NetworkInfo(id=name, name=name, driver="bridge", internal=False, labels=labels)
        )
        return True

    async def remove_network(self, name: str) -> bool:
        before = len(self.networks)
        self.networks = [n for n in self.networks if n.name != name]
        return len(self.networks) < before

    async def architecture(self) -> str:
        return self.arch

    async def image_platforms(self, ref: str) -> list[str] | None:
        return self.platforms.get(ref)

    async def list_containers(self, labels: dict[str, str] | None = None) -> list[ContainerInfo]:
        wanted = (labels or {}).items()
        return [c for c in self.containers.values() if wanted <= c.labels.items()]

    async def get_container(self, container_id: str) -> ContainerInfo:
        try:
            return self.containers[container_id]
        except KeyError:
            raise ContainerNotFoundError(container_id) from None

    async def events(self, since: datetime | None = None) -> AsyncGenerator[DockerEvent, None]:
        queue: asyncio.Queue[DockerEvent | None] = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while (event := await queue.get()) is not None:
                yield event
        finally:
            self._subscribers.remove(queue)

    async def stats_once(self, container_id: str) -> StatsSample:
        await self.get_container(container_id)
        return self.stats.get(container_id) or StatsSample(0.0, 0, 0, 0, 0)

    async def logs(
        self, container_id: str, *, follow: bool = False, tail: int | str = 200,
        since: int | None = None, timestamps: bool = False,
    ) -> AsyncIterator[str]:  # fmt: skip
        """Stored lines as given (tests write them with their timestamps)."""
        lines = self.logs_by_container.get(container_id, [])
        for line in lines if tail == "all" else lines[-int(tail) :] if tail else []:
            yield line

    async def open_exec(self, container_id: str, cmd: list[str]) -> ExecSession:
        await self.get_container(container_id)
        session = FakeExecSession(cmd)
        self.execs.append(session)
        return session

    async def exec_run(
        self, container_id: str, cmd: list[str], user: str | None = None
    ) -> tuple[int, str]:
        await self.get_container(container_id)
        self.exec_calls.append(cmd)
        return self.exec_results.get(" ".join(cmd), (0, ""))

    async def list_networks(self) -> list[NetworkInfo]:
        return list(self.networks)

    async def close(self) -> None:
        self.disconnect()
