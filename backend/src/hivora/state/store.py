"""In-memory runtime state. Never persisted: Docker is the source of truth."""

from collections.abc import Mapping, Set
from dataclasses import dataclass

from hivora.docker_gateway import ContainerInfo
from hivora.state.status import AppStatus, aggregate_status

LABEL_APP = "io.hivora.app"
LABEL_ZONE = "io.hivora.zone"
LABEL_REVISION = "io.hivora.revision"
LABEL_COMPOSE_PROJECT = "com.docker.compose.project"


def app_key_from_labels(labels: Mapping[str, str], adopted: Set[str] = frozenset()) -> str | None:
    """Hivora apps are keyed by ``io.hivora.app``, adopted stacks (``adopted``: their
    compose projects) by their project, other compose stacks (adoption candidates) by
    ``compose:<project>``. The running panel asks its StateStore, which knows the
    adopted projects (``StateStore.key_of``)."""
    if slug := labels.get(LABEL_APP):
        return slug
    if project := labels.get(LABEL_COMPOSE_PROJECT):
        return project if project in adopted else f"compose:{project}"
    return None


def app_key(container: ContainerInfo, adopted: Set[str] = frozenset()) -> str | None:
    return app_key_from_labels(container.labels, adopted)


@dataclass(frozen=True, slots=True)
class AppState:
    key: str
    status: AppStatus
    containers: tuple[ContainerInfo, ...]


class StateStore:
    def __init__(self) -> None:
        self._containers: dict[str, ContainerInfo] = {}
        # Containers stopped through the API since their last start. Docker's
        # state cannot tell a requested stop from a crash; its events can.
        self._stop_requested: set[str] = set()
        # Compose projects adopted as Hivora apps: keyed by the project name (their slug).
        self._adopted: set[str] = set()

    def set_adopted(self, projects: set[str]) -> None:
        self._adopted.clear()
        self._adopted.update(projects)

    def key_of(self, container: ContainerInfo) -> str | None:
        """The app a container belongs to (see ``app_key_from_labels``)."""
        return app_key(container, self._adopted)

    def key_from_labels(self, labels: Mapping[str, str]) -> str | None:
        return app_key_from_labels(labels, self._adopted)

    def mark_stop_requested(self, container_id: str) -> None:
        self._stop_requested.add(container_id)

    def clear_stop_requested(self, container_id: str) -> None:
        self._stop_requested.discard(container_id)

    def replace_all(self, containers: list[ContainerInfo]) -> None:
        self._containers = {c.id: c for c in containers}
        self._stop_requested &= self._containers.keys()

    def upsert(self, container: ContainerInfo) -> None:
        self._containers[container.id] = container

    def remove(self, container_id: str) -> ContainerInfo | None:
        self._stop_requested.discard(container_id)
        return self._containers.pop(container_id, None)

    def get(self, container_id: str) -> ContainerInfo | None:
        return self._containers.get(container_id)

    def containers(self) -> list[ContainerInfo]:
        return list(self._containers.values())

    def unmanaged(self) -> list[ContainerInfo]:
        """Standalone containers, outside any Hivora app or compose project (Hivora's
        own containers, the panel and its host agent, are not counted)."""
        return [c for c in self._containers.values()
                if self.key_of(c) is None and not c.labels.get("io.hivora.self")]  # fmt: skip

    def app(self, key: str) -> AppState:
        members = tuple(c for c in self._containers.values() if self.key_of(c) == key)
        return AppState(key, aggregate_status(members, self._stop_requested), members)

    def apps(self) -> dict[str, AppState]:
        keys = {k for c in self._containers.values() if (k := self.key_of(c))}
        return {k: self.app(k) for k in sorted(keys)}
