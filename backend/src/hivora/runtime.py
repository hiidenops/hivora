"""Assembles every service of a running Hivora and manages their lifecycle."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hivora.apps import AppJobHandlers, AppService
from hivora.apps.custom_images import check_images
from hivora.apps.zone_actions import ZoneActions
from hivora.audit import AuditRecorder
from hivora.auth.service import AuthService
from hivora.backups.service import BackupService
from hivora.compose_runner import ComposeRunner
from hivora.core.clock import Clock, SystemClock
from hivora.core.config import Settings
from hivora.core.events import EventBus
from hivora.crypto.cipher import SecretBox, load_or_create_master_key
from hivora.db.engine import make_engine, make_sessionmaker
from hivora.db.migrate import SchemaTooNewError, db_revision, schema_state, upgrade_to_head
from hivora.docker_gateway import DockerGateway
from hivora.games.modpacks import ModpackCatalog
from hivora.games.worlds import WorldJobs
from hivora.hostfw.blocking import Blocking
from hivora.hostfw.connections import register_conntrack
from hivora.hostfw.service import HostFirewall
from hivora.hostfw.static_routes import StaticRoutes
from hivora.jobs import JobQueue
from hivora.metrics.apps import AppMetrics
from hivora.metrics.host import HostMetrics
from hivora.sites import SiteContent
from hivora.sites.config import SiteConfig
from hivora.sites.files import SiteFiles
from hivora.sites.hosting import SiteHosting
from hivora.sites.ports import site_ports
from hivora.state import StateService
from hivora.system.panel_backup import backup_panel
from hivora.system.public_address import PublicAddress
from hivora.system.secrets import SecretSettings
from hivora.tasks.service import TaskTools, run_scheduler
from hivora.templates import Catalog
from hivora.templates.icons import IconCache
from hivora.vpn.admin import AdminVpn, follow_admin_client
from hivora.vpn.service import VpnTools, expire_clients, follow_deploys

if TYPE_CHECKING:
    from hivora.realtime.console import ConsoleManager

logger = logging.getLogger(__name__)


def prepare_database(settings: Settings) -> None:
    """Before anything opens the database (server or ``bootstrap``): refuse a database
    from a newer Hivora, back the panel up when a migration is pending, then migrate."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    schema = schema_state(settings.db_path)
    if schema == "newer":  # an older image on a newer database: touch nothing
        raise SchemaTooNewError(db_revision(settings.db_path) or "?")
    if schema == "behind":  # a migration is about to run: keep a way back
        logger.warning("panel backed up before migrating: %s", backup_panel(settings.data_dir))
    upgrade_to_head(settings.db_path)


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
    backups: BackupService
    sites: SiteContent
    site_files: SiteFiles
    site_config: SiteConfig
    site_hosting: SiteHosting
    tasks: TaskTools
    vpn: VpnTools
    hostfw: HostFirewall
    blocking: Blocking
    static_routes: StaticRoutes
    zone_actions: ZoneActions
    admin_vpn: AdminVpn
    _icons_task: "asyncio.Task[None] | None" = field(default=None, init=False)
    _vpn_tasks: "list[asyncio.Task[None]]" = field(default_factory=list, init=False)
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
        compose_cmd: Sequence[str] | None = None,
        compose_env: dict[str, str] | None = None,
        clock: Clock | None = None,
    ) -> "Runtime":
        """Synchronous wiring: migrations, keys and catalog; nothing started yet."""
        clock = clock or SystemClock()
        prepare_database(settings)
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
        runner = ComposeRunner(settings.apps_dir, compose_cmd=compose_cmd or settings.compose_cmd,
                               env=compose_env)  # fmt: skip
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
        )
        # What only the planner and the job handlers use, given to them here.
        apps.planner.secret_settings = secrets
        apps.planner.public_address = public_address.current
        apps.gateway = gateway
        AppJobHandlers(apps).register()
        WorldJobs(apps).register()
        backups = BackupService(apps)
        backups.register()
        sites = SiteContent(sessions=sessions, jobs=jobs, settings=settings, bus=bus)
        sites.register()
        site_files = SiteFiles(sessions=sessions, jobs=jobs, settings=settings, bus=bus)
        site_files.register()
        site_config = SiteConfig(sessions=sessions, jobs=jobs, gateway=gateway, state=state.store,
                                 settings=settings, bus=bus)  # fmt: skip
        site_config.register()
        apps.planner.site_ports = site_ports  # the hosts publish their sites' ports
        site_hosting = SiteHosting(sessions=sessions, revisions=apps.revisions, jobs=jobs,
                                   bus=bus, clock=clock, settings=settings,
                                   state=state.store)  # fmt: skip
        auth = AuthService(settings=settings, sessions=sessions, box=box, bus=bus, clock=clock)
        audit = AuditRecorder(sessions, bus)
        icons = IconCache(settings.data_dir / "icons")
        tasks = TaskTools(sessions=sessions, clock=clock, bus=bus, settings=settings, apps=apps,
                          backups=backups, box=box, store=state.store, gateway=gateway)  # fmt: skip
        vpn = VpnTools(sessions=sessions, apps=apps, box=box, bus=bus, clock=clock,
                       gateway=gateway)  # fmt: skip
        hostfw = HostFirewall(sessions=sessions, gateway=gateway, bus=bus, store=state.store)
        register_conntrack(hostfw, jobs)  # the conntrack install job
        blocking = Blocking(
            fw=hostfw,
            sessions=sessions,
            jobs=jobs,
            bus=bus,
            clock=clock,
            store=state.store,
            host_ips=lambda: [settings.host_lan_ip, public_address.current()],
        )
        blocking.register()  # the host_firewall job
        static_routes = StaticRoutes(fw=hostfw, sessions=sessions, jobs=jobs, bus=bus, clock=clock)
        static_routes.register()  # the host_route job
        zone_actions = ZoneActions(sessions=sessions, jobs=jobs, lifecycle=apps.lifecycle,
                                   store=state.store, bus=bus)  # fmt: skip
        zone_actions.register()  # the zone_action job
        admin_vpn = AdminVpn(settings=settings, sessions=sessions, apps=apps, vpn=vpn, jobs=jobs,
                             public_address=public_address.current, clock=clock)  # fmt: skip
        return cls(settings, clock, bus, engine, sessions, box, catalog, gateway, state, runner,
                   jobs, apps, auth, audit, icons, HostMetrics(bus), secrets,
                   ModpackCatalog(settings.data_dir / "icons" / "modpacks"),
                   public_address, AppMetrics(gateway, state.store, bus), backups,
                   sites, site_files, site_config, site_hosting, tasks, vpn, hostfw,
                   blocking, static_routes, zone_actions, admin_vpn)  # fmt: skip

    async def start(self) -> None:
        # Icons download in the background: startup never waits for the network.
        self._icons_task = asyncio.create_task(self._warm_icons())
        await self.audit.start()
        await self.metrics.start()
        await self.public_address.start()
        await self.app_metrics.start()
        await self.backups.start()
        await self.site_config.start()
        await self.auth.ensure_initial_admin()
        await self.apps.custom.load_templates()
        await self.apps.adoption.load()
        try:
            self.catalog.set_host_arch(await self.gateway.architecture())
        except Exception:
            logger.warning("Docker did not report its architecture; using the local one")
        await self.state.start()
        self._vpn_tasks = [
            asyncio.create_task(follow_deploys(self.vpn), name="vpn-follow"),
            asyncio.create_task(expire_clients(self.vpn), name="vpn-expiry"),
            asyncio.create_task(run_scheduler(self.tasks), name="task-scheduler"),
            asyncio.create_task(check_images(self.apps.custom), name="free-image-updates"),
            asyncio.create_task(follow_admin_client(self.admin_vpn, self.bus), name="admin-conf"),
        ]
        await self.blocking.reapply()  # the host may have rebooted: its rules are gone
        await self.static_routes.reapply()  # and its static routes
        await self.jobs.start()
        # The vpn modes: the admin VPN needs the job queue running (its deploy is a job).
        self._vpn_tasks.append(asyncio.create_task(self.admin_vpn.ensure(), name="admin-vpn"))

    async def tasks_tick(self) -> None:
        """Run the scheduled tasks that are due (the scheduler calls this every minute)."""
        await self.tasks.tick()

    async def _warm_icons(self) -> None:
        try:
            await self.icons.warm(self.catalog.entries())
        except Exception:
            logger.exception("icon cache warm-up failed")

    async def stop(self) -> None:
        for task in (self._icons_task, *self._vpn_tasks):
            if task:
                task.cancel()
        await self.jobs.stop()
        await self.metrics.stop()
        await self.public_address.stop()
        await self.app_metrics.stop()
        await self.backups.stop()
        await self.site_config.stop()
        await self.state.stop()
        await self.audit.stop()
        await self.gateway.close()
        await self.engine.dispose()
