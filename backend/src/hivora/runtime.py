"""Assembles every service of a running Hivora and manages their lifecycle."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hivora.apps import AppJobHandlers, AppService
from hivora.audit import AuditRecorder
from hivora.auth.service import AuthService
from hivora.compose_runner import ComposeRunner
from hivora.core.clock import Clock, SystemClock
from hivora.core.config import Settings
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox, load_or_create_master_key
from hivora.db.engine import make_engine, make_sessionmaker
from hivora.db.migrate import upgrade_to_head
from hivora.docker_gateway import DockerGateway
from hivora.jobs import JobQueue
from hivora.state import StateService
from hivora.templates import Catalog

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    clock: Clock
    bus: EventBus
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    box: SecretBox
    catalog: Catalog
    gateway: DockerGateway
    state: StateService
    runner: ComposeRunner
    jobs: JobQueue
    apps: AppService
    auth: AuthService
    audit: AuditRecorder

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        gateway: DockerGateway | None = None,
        compose_cmd: Sequence[str] = ("docker", "compose"),
        compose_env: dict[str, str] | None = None,
        clock: Clock | None = None,
    ) -> "Runtime":
        """Synchronous wiring: migrations, keys and catalog; nothing started yet."""
        clock = clock or SystemClock()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        upgrade_to_head(settings.db_path)
        engine = make_engine(settings.db_path)
        sessions = make_sessionmaker(engine)
        box = SecretBox(load_or_create_master_key(settings.secret_key_path))
        bus = EventBus()
        catalog = Catalog()
        if settings.catalog_dir.is_dir():
            for error in catalog.load_directory(settings.catalog_dir):
                logger.error("template skipped", extra={"error": error})
        if gateway is None:
            from hivora.docker_gateway.local import LocalDockerGateway  # lazy: aiohttp

            gateway = LocalDockerGateway()
        state = StateService(gateway, bus)
        runner = ComposeRunner(settings.apps_dir, compose_cmd=compose_cmd, env=compose_env)
        jobs = JobQueue(sessions, bus, clock=clock, workers=settings.job_workers)
        apps = AppService(
            settings=settings,
            sessions=sessions,
            catalog=catalog,
            runner=runner,
            state=state.store,
            jobs=jobs,
            box=box,
            bus=bus,
            clock=clock,
        )
        AppJobHandlers(apps).register()
        auth = AuthService(settings=settings, sessions=sessions, box=box, bus=bus, clock=clock)
        audit = AuditRecorder(sessions, bus)
        return cls(settings, clock, bus, engine, sessions, box, catalog, gateway, state, runner,
                   jobs, apps, auth, audit)  # fmt: skip

    async def start(self) -> None:
        await self.audit.start()
        await self.auth.ensure_initial_admin()
        await self.state.start()
        await self.jobs.start()

    async def stop(self) -> None:
        await self.jobs.stop()
        await self.state.stop()
        await self.audit.stop()
        await self.gateway.close()
        await self.engine.dispose()
