"""Transport-agnostic Docker interface.

V1 talks to the local socket; V4 will add a remote-agent implementation
without touching the other modules.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import datetime

from hivora.core.errors import HivoraError, NotFoundError
from hivora.docker_gateway.models import ContainerInfo, DockerEvent, NetworkInfo, StatsSample


class DockerUnavailableError(HivoraError):
    code = "docker_unavailable"


class ContainerNotFoundError(NotFoundError):
    code = "container_not_found"


class DockerGateway(ABC):
    @abstractmethod
    async def ping(self) -> str:
        """Return the Engine version; raise DockerUnavailableError if unreachable."""

    @abstractmethod
    async def list_containers(self, labels: dict[str, str] | None = None) -> list[ContainerInfo]:
        """All containers (running or not), optionally filtered by label equality."""

    @abstractmethod
    async def get_container(self, container_id: str) -> ContainerInfo:
        """Raise ContainerNotFoundError when absent."""

    @abstractmethod
    def events(self, since: datetime | None = None) -> AsyncGenerator[DockerEvent, None]:
        """Live event stream, replaying events from ``since`` first when given.

        Ends (or raises) when the connection drops.
        """

    @abstractmethod
    async def stats_once(self, container_id: str) -> StatsSample:
        """A single stats sample: never keep permanent stats streams open."""

    @abstractmethod
    def logs(
        self, container_id: str, *, follow: bool = False, tail: int = 200
    ) -> AsyncIterator[str]:
        """Container output lines (stdout and stderr)."""

    @abstractmethod
    async def list_networks(self) -> list[NetworkInfo]: ...

    @abstractmethod
    async def close(self) -> None: ...
