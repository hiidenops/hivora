"""Adoption of compose stacks already running on this Docker: Hivora links them
(metadata only) and drives their lifecycle by project name, nothing is redeployed."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import LABEL_COMPOSE_SERVICE
from hivora.apps.models import (
    Application,
    DesiredState,
    Exposure,
    Origin,
    PortBinding,
    Service,
    ServiceRole,
)
from hivora.compose_runner.runner import validate_slug
from hivora.core.clock import Clock
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.core.events import EventBus
from hivora.docker_gateway import ContainerInfo, ContainerState
from hivora.state import StateStore
from hivora.zones import get_zone

LABEL_COMPOSE_PROJECT = "com.docker.compose.project"
LABEL_WORKING_DIR = "com.docker.compose.project.working_dir"


@dataclass(frozen=True, slots=True)
class Candidate:
    """A compose stack Hivora could adopt."""

    project: str
    services: list[str]
    running: int
    containers: int
    working_dir: str | None  # where its compose file lives on the host (label)


class Adoption:
    def __init__(self, *, sessions: async_sessionmaker[AsyncSession], state: StateStore,
                 bus: EventBus, clock: Clock) -> None:  # fmt: skip
        self.sessions = sessions
        self.state = state
        self.bus = bus
        self.clock = clock

    def candidates(self) -> list[Candidate]:
        """Compose stacks running on this Docker that Hivora does not manage yet."""
        groups: dict[str, list[ContainerInfo]] = {}
        for c in self.state.containers():
            project = c.labels.get(LABEL_COMPOSE_PROJECT)
            if not project or c.labels.get("io.hivora.app") or c.labels.get("io.hivora.self"):
                continue
            if self.state.key_of(c) != f"compose:{project}":
                continue  # already adopted
            groups.setdefault(project, []).append(c)
        out = []
        for project, cs in sorted(groups.items()):
            services = sorted({c.labels.get(LABEL_COMPOSE_SERVICE, c.name) for c in cs})
            running = sum(c.state is ContainerState.RUNNING for c in cs)
            where = next((w for c in cs if (w := c.labels.get(LABEL_WORKING_DIR))), None)
            out.append(Candidate(project, services, running, len(cs), where))
        return out

    async def adopt(self, project: str, name: str, zone_slug: str | None) -> Application:
        """Link a running stack to Hivora (metadata only: nothing is redeployed)."""
        found = next((c for c in self.candidates() if c.project == project), None)
        if found is None:
            raise NotFoundError("no such compose stack to adopt", project=project)
        try:
            validate_slug(project)
        except ValidationError:
            raise ValidationError("this project name cannot be an app id",
                                  project=project) from None  # fmt: skip
        containers = [c for c in self.state.containers()
                      if c.labels.get(LABEL_COMPOSE_PROJECT) == project]  # fmt: skip
        async with self.sessions() as session, session.begin():
            if await session.scalar(select(Application.id).where(Application.slug == project)):
                raise ConflictError("an app already uses this name", slug=project)
            zone = await get_zone(session, zone_slug) if zone_slug else None
            app = Application(
                slug=project, name=name or project, zone_id=zone.id if zone else None,
                origin=Origin.ADOPTED, template_version_id=None,
                desired_state=DesiredState.RUNNING, icon=None, notes="",
                created_at=self.clock.now(), services=_services_from_containers(containers),
            )  # fmt: skip
            session.add(app)
        await self.load()
        self.bus.publish("app.adopted", app=project, containers=len(containers))
        return app

    async def load(self) -> None:
        """The state keys adopted stacks by project name: tell it which ones."""
        async with self.sessions() as session:
            slugs = await session.scalars(
                select(Application.slug).where(Application.origin == Origin.ADOPTED)
            )
            self.state.set_adopted(set(slugs))


def _services_from_containers(containers: list[ContainerInfo]) -> list[Service]:
    """Services of an adopted stack, as its containers show them (image, published ports)."""
    by_service: dict[str, ContainerInfo] = {}
    for c in containers:
        by_service.setdefault(c.labels.get(LABEL_COMPOSE_SERVICE, c.name), c)
    out: list[Service] = []
    everywhere = {None, "0.0.0.0", "::"}  # noqa: S104 (reading Docker's bindings)
    for name, c in sorted(by_service.items()):
        unique = {(p.container_port, p.protocol, p.host_port): p for p in c.ports}.values()
        ports = [
            PortBinding(host_ip=None if p.host_ip in everywhere else p.host_ip,
                        host_port=p.host_port, container_port=p.container_port,
                        protocol=p.protocol, purpose="other",
                        exposure=Exposure.PUBLIC if p.host_ip in everywhere else Exposure.LAN)
            for p in unique if p.host_port
        ]  # fmt: skip
        out.append(Service(name=name, image=c.image, role=ServiceRole.MAIN if not out
                           else ServiceRole.SIDECAR, restart_policy="unknown", ports=ports,
                           volumes=[]))  # fmt: skip
    return out
