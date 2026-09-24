"""Normalized views of Docker objects, independent of the transport."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ContainerState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    RESTARTING = "restarting"
    REMOVING = "removing"
    EXITED = "exited"
    DEAD = "dead"


class Health(StrEnum):
    NONE = "none"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class PublishedPort:
    container_port: int
    protocol: str
    host_ip: str | None = None
    host_port: int | None = None


@dataclass(frozen=True, slots=True)
class ContainerInfo:
    id: str
    name: str
    image: str
    state: ContainerState
    health: Health = Health.NONE
    exit_code: int | None = None
    labels: dict[str, str] = field(default_factory=dict)
    ports: tuple[PublishedPort, ...] = ()
    networks: tuple[str, ...] = ()
    started_at: datetime | None = None  # from inspect; container listings omit it


@dataclass(frozen=True, slots=True)
class DockerEvent:
    """A raw Docker event: ``type`` is container, network, image, volume..."""

    type: str
    action: str
    actor_id: str
    attributes: dict[str, str] = field(default_factory=dict)
    time: datetime | None = None


@dataclass(frozen=True, slots=True)
class StatsSample:
    cpu_percent: float
    mem_bytes: int
    mem_limit: int
    net_rx: int
    net_tx: int


@dataclass(frozen=True, slots=True)
class NetworkInfo:
    id: str
    name: str
    driver: str
    internal: bool
    labels: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
