"""DockerGateway over the local Engine API socket, via aiodocker."""

import json
import re
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from typing import Any

import aiodocker
import aiohttp

from hivora.docker_gateway.base import (
    ContainerNotFoundError,
    DockerGateway,
    DockerUnavailableError,
)
from hivora.docker_gateway.models import (
    ContainerInfo,
    ContainerState,
    DockerEvent,
    Health,
    NetworkInfo,
    PublishedPort,
    StatsSample,
)

_EXIT_CODE = re.compile(r"^Exited \((-?\d+)\)")
_HEALTH_IN_STATUS = (
    ("(healthy)", Health.HEALTHY),
    ("(unhealthy)", Health.UNHEALTHY),
    ("(health: starting)", Health.STARTING),
)


def _state(value: str) -> ContainerState:
    try:
        return ContainerState(value)
    except ValueError:
        return ContainerState.DEAD


def _health(value: str | None) -> Health:
    try:
        return Health(value) if value else Health.NONE
    except ValueError:
        return Health.NONE


def container_from_summary(raw: dict[str, Any]) -> ContainerInfo:
    """Parse an item of ``GET /containers/json``."""
    status: str = raw.get("Status") or ""
    health = _health((raw.get("Health") or {}).get("Status"))
    if health is Health.NONE:  # Engines older than API 1.52 only expose it in Status
        health = next((h for marker, h in _HEALTH_IN_STATUS if marker in status), Health.NONE)
    exit_match = _EXIT_CODE.match(status)
    ports = tuple(
        PublishedPort(
            container_port=p["PrivatePort"],
            protocol=p.get("Type", "tcp"),
            host_ip=p.get("IP"),
            host_port=p.get("PublicPort"),
        )
        for p in raw.get("Ports") or []
    )
    networks = tuple(((raw.get("NetworkSettings") or {}).get("Networks") or {}).keys())
    return ContainerInfo(
        id=raw["Id"],
        name=(raw.get("Names") or ["/"])[0].lstrip("/"),
        image=raw.get("Image", ""),
        state=_state(raw.get("State", "")),
        health=health,
        exit_code=int(exit_match.group(1)) if exit_match else None,
        labels=raw.get("Labels") or {},
        ports=ports,
        networks=networks,
    )


def container_from_inspect(raw: dict[str, Any]) -> ContainerInfo:
    """Parse ``GET /containers/{id}/json``."""
    st = raw.get("State") or {}
    state = _state(st.get("Status", ""))
    ports: list[PublishedPort] = []
    for key, bindings in ((raw.get("NetworkSettings") or {}).get("Ports") or {}).items():
        port, _, proto = key.partition("/")
        for b in bindings or [None]:
            ports.append(
                PublishedPort(
                    container_port=int(port),
                    protocol=proto or "tcp",
                    host_ip=b.get("HostIp") if b else None,
                    host_port=int(b["HostPort"]) if b and b.get("HostPort") else None,
                )
            )
    return ContainerInfo(
        id=raw["Id"],
        name=raw.get("Name", "").lstrip("/"),
        image=(raw.get("Config") or {}).get("Image", ""),
        state=state,
        health=_health((st.get("Health") or {}).get("Status")),
        exit_code=st.get("ExitCode")
        if state in (ContainerState.EXITED, ContainerState.DEAD)
        else None,
        labels=(raw.get("Config") or {}).get("Labels") or {},
        ports=tuple(ports),
        networks=tuple(((raw.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
    )


def stats_from_raw(raw: dict[str, Any]) -> StatsSample:
    cpu, pre = raw.get("cpu_stats") or {}, raw.get("precpu_stats") or {}
    cpu_delta = (cpu.get("cpu_usage") or {}).get("total_usage", 0) - (
        pre.get("cpu_usage") or {}
    ).get("total_usage", 0)
    sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    online = cpu.get("online_cpus") or 1
    cpu_percent = (cpu_delta / sys_delta) * online * 100 if sys_delta > 0 and cpu_delta > 0 else 0.0
    mem = raw.get("memory_stats") or {}
    # Match `docker stats`: exclude reclaimable page cache.
    usage = mem.get("usage", 0) - (mem.get("stats") or {}).get("inactive_file", 0)
    nets = (raw.get("networks") or {}).values()
    return StatsSample(
        cpu_percent=round(cpu_percent, 2),
        mem_bytes=max(usage, 0),
        mem_limit=mem.get("limit", 0),
        net_rx=sum(n.get("rx_bytes", 0) for n in nets),
        net_tx=sum(n.get("tx_bytes", 0) for n in nets),
    )


def event_from_raw(raw: dict[str, Any]) -> DockerEvent:
    actor = raw.get("Actor") or {}
    ts = raw.get("timeNano")
    return DockerEvent(
        type=raw.get("Type", ""),
        # health events look like "health_status: healthy"
        action=raw.get("Action", ""),
        actor_id=actor.get("ID", ""),
        attributes=actor.get("Attributes") or {},
        time=datetime.fromtimestamp(ts / 1e9, UTC) if ts else None,
    )


class LocalDockerGateway(DockerGateway):
    """Talks to the Engine API through aiodocker's low-level ``_query`` helpers.

    aiodocker's high-level wrappers either hide the raw JSON we normalize
    ourselves or share one events channel between all callers; the raw
    endpoints keep this module independent from those choices.
    """

    def __init__(self, url: str | None = None) -> None:
        # None lets aiodocker honour DOCKER_HOST, then the default unix socket.
        self._docker = aiodocker.Docker(url=url)

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return await self._docker._query_json(path, params=params)
        except aiodocker.DockerError as exc:
            if exc.status == 404:
                raise ContainerNotFoundError(path) from exc
            raise
        except (OSError, aiohttp.ClientError) as exc:
            raise DockerUnavailableError(str(exc)) from exc

    async def ping(self) -> str:
        info = await self._get_json("version")
        return str(info.get("Version", "unknown"))

    async def list_containers(self, labels: dict[str, str] | None = None) -> list[ContainerInfo]:
        params: dict[str, Any] = {"all": "true"}
        if labels:
            params["filters"] = json.dumps({"label": [f"{k}={v}" for k, v in labels.items()]})
        return [container_from_summary(c) for c in await self._get_json("containers/json", params)]

    async def get_container(self, container_id: str) -> ContainerInfo:
        return container_from_inspect(await self._get_json(f"containers/{container_id}/json"))

    async def events(self, since: datetime | None = None) -> AsyncGenerator[DockerEvent, None]:
        params = {"since": f"{since.timestamp():.9f}"} if since else None
        try:
            async with self._docker._query("events", params=params, timeout=None) as response:
                async for line in response.content:
                    if line.strip():
                        yield event_from_raw(json.loads(line))
        except (OSError, aiohttp.ClientError) as exc:
            raise DockerUnavailableError(str(exc)) from exc

    async def stats_once(self, container_id: str) -> StatsSample:
        raw = await self._get_json(f"containers/{container_id}/stats", {"stream": "false"})
        return stats_from_raw(raw)

    async def logs(
        self, container_id: str, *, follow: bool = False, tail: int = 200
    ) -> AsyncIterator[str]:
        container = self._docker.containers.container(container_id)
        if follow:
            async for line in container.log(stdout=True, stderr=True, follow=True, tail=tail):
                yield line.rstrip("\n")
        else:
            for line in await container.log(stdout=True, stderr=True, tail=tail):
                yield line.rstrip("\n")

    async def list_networks(self) -> list[NetworkInfo]:
        return [
            NetworkInfo(
                id=n["Id"],
                name=n["Name"],
                driver=n.get("Driver", ""),
                internal=bool(n.get("Internal")),
                labels=n.get("Labels") or {},
                options=n.get("Options") or {},
            )
            for n in await self._docker.networks.list()
        ]

    async def close(self) -> None:
        await self._docker.close()
