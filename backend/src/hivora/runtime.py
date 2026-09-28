"""Assembles every service of a running Hivora and manages their lifecycle."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
from hivora.games.modpacks import ModpackCatalog
from hivora.games.worlds import WorldJobs
from hivora.jobs import JobQueue
from hivora.metrics.apps import AppMetrics
from hivora.metrics.host import HostMetrics
from hivora.state import StateService
from hivora.system.public_address import PublicAddress
from hivora.system.secrets import SecretSettings
from hivora.templates import Catalog
from hivora.templates.catalog import set_host_arch
from hivora.templates.icons import IconCache

if TYPE_CHECKING:
    from hivora.realtime.console import ConsoleManager

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
    icons: IconCache
    metrics: HostMetrics
    secrets: SecretSettings
    modpacks: ModpackCatalog
    public_address: PublicAddress
    app_metrics: AppMetrics
    _icons_task: "asyncio.Task[None] | None" = field(default=None, init=False)
    _vpn_task: "asyncio.Task[None] | None" = field(default=None, init=False)
    consoles: "ConsoleManager" = field(init=False)

    def __post_init__(self) -> None:
        from hivora.realtime.console import ConsoleManager  # needs Runtime itself

        self.consoles = ConsoleManager(self)

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
        secrets = SecretSettings(sessions, box, bus)
        public_address = PublicAddress(sessions, settings.host_public_ip)
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
            secret_settings=secrets,
            public_address=public_address.current,
            gateway=gateway,
        )
        AppJobHandlers(apps).register()
        WorldJobs(apps).register()
        auth = AuthService(settings=settings, sessions=sessions, box=box, bus=bus, clock=clock)
        audit = AuditRecorder(sessions, bus)
        icons = IconCache(settings.data_dir / "icons")
        return cls(settings, clock, bus, engine, sessions, box, catalog, gateway, state, runner,
                   jobs, apps, auth, audit, icons, HostMetrics(bus), secrets,
                   ModpackCatalog(settings.data_dir / "icons" / "modpacks"),
                   public_address, AppMetrics(gateway, state.store, bus))  # fmt: skip

    async def start(self) -> None:
        # Icons download in the background: startup never waits for the network.
        self._icons_task = asyncio.create_task(self._warm_icons())
        await self.audit.start()
        await self.metrics.start()
        await self.public_address.start()
        await self.app_metrics.start()
        await self.auth.ensure_initial_admin()
        await self.apps.load_custom_templates()
        try:
            set_host_arch(await self.gateway.architecture())
        except Exception:
            logger.warning("Docker did not report its architecture; using the local one")
        await self.state.start()
        from hivora.vpn.service import follow_deploys  # needs Runtime itself

        self._vpn_task = asyncio.create_task(follow_deploys(self), name="vpn-follow")
        await self.jobs.start()

    async def _warm_icons(self) -> None:
        try:
            await self.icons.warm(self.catalog.entries())
        except Exception:
            logger.exception("icon cache warm-up failed")

    async def stop(self) -> None:
        for task in (self._icons_task, self._vpn_task):
            if task:
                task.cancel()
        await self.jobs.stop()
        await self.metrics.stop()
        await self.public_address.stop()
        await self.app_metrics.stop()
        await self.state.stop()
        await self.audit.stop()
        await self.gateway.close()
        await self.engine.dispose()
