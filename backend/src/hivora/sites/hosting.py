"""The sites an nginx app hosts: add one on its own port, move or remove it, turn it on or
off, give it a server name.

A site's port is published by the app's next revision (the planner adds the sites' ports
to every compile): adding, moving or removing a site makes a revision whose job recreates
the container (about a second without any site), then the site_config job writes nginx's
files. Turning a site on or off, or naming it, only rewrites those files: its port stays
published. Each change is one transaction (rows, revision, jobs) or nothing at all;
``plan`` shows a change, recreation included, without writing anything.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import PortConflictError, conflict_dict, get_app, latest_revision, slugify
from hivora.apps.models import Application, DesiredState
from hivora.apps.queries import template_slug
from hivora.apps.revisions import Revisions
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError
from hivora.core.events import EventBus
from hivora.jobs import Job, JobKind, JobQueue
from hivora.sites import core, nginx
from hivora.sites.models import Site
from hivora.templates.overrides import Overrides

MAX_SITES = 30  # added sites per host (the main site aside)


class SiteExistsError(ConflictError):
    code = "site_exists"


class TooManySitesError(ConflictError):
    code = "too_many_sites"


class MainSiteError(ConflictError):
    code = "main_site_fixed"


class HostStoppedError(ConflictError):
    code = "site_host_stopped"


class NotNginxError(ConflictError):
    code = "not_a_nginx_app"


@dataclass(frozen=True, slots=True)
class HostedSite:
    id: int
    slug: str
    name: str
    main: bool
    port: int | None  # the main site: the app's web port
    server_name: str | None
    enabled: bool
    url: str | None  # on the host's LAN address, when it is known


@dataclass(frozen=True, slots=True)
class SiteHost:
    app_id: int
    slug: str
    name: str
    upgrade_required: bool  # nginx still on template 1.0.0: only its main site
    stopped: bool  # port changes are refused until it is started
    max_sites: int
    sites: list[HostedSite]


@dataclass(frozen=True, slots=True)
class SitePlan:
    recreate: bool  # the container is recreated: every site of this nginx stops ~1 s
    revision: int | None  # the revision this change makes (None: no new revision)
    diff: str
    ports_before: list[int]
    ports_after: list[int]


Change = Callable[[AsyncSession, int], Awaitable[Site]]  # one change to a host's sites


class SiteHosting:
    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], revisions: Revisions,
        jobs: JobQueue, bus: EventBus, clock: Clock, settings: Settings,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.revisions = revisions
        self.jobs = jobs
        self.bus = bus
        self.clock = clock
        self.settings = settings

    # --- reading, and turning an nginx into a host ---------------------------------

    async def view(self, app_id: int) -> SiteHost:
        """A host and its sites, the main one first (404 for an app that hosts none)."""
        async with self.sessions() as session:
            return await self._view(session, app_id)

    async def _view(self, session: AsyncSession, app_id: int) -> SiteHost:
        app = await core.get_site(session, app_id)
        try:
            await core.conf_dir(session, app.id)
            upgrade_required = False
        except core.HostUpgradeRequiredError:
            upgrade_required = True
        rows = await session.scalars(
            select(Site).where(Site.app_id == app.id).order_by(Site.root != "", Site.id)
        )
        web_port = (await _inputs(session, app.id)).get("web_port")
        lan = self.settings.host_lan_ip
        sites = []
        main_port = int(web_port) if web_port is not None else None
        for r in rows:
            port = main_port if r.root == "" else r.port
            url = f"http://{lan}:{port}" if lan and port else None
            sites.append(HostedSite(r.id, r.slug, r.name, r.root == "", port, r.server_name,
                                    r.enabled, url))  # fmt: skip
        return SiteHost(app.id, app.slug, app.name, upgrade_required,
                        app.desired_state is DesiredState.STOPPED, MAX_SITES, sites)  # fmt: skip

    async def enable_hosting(self, app_id: int) -> SiteHost:
        """An nginx deployed from the catalog becomes a host: its html volume is its main
        site. Nothing is redeployed; a host already is one (no change)."""
        async with self.sessions() as session, session.begin():
            app = await get_app(session, app_id)
            if await template_slug(session, app) != "nginx":
                raise NotNginxError("only an nginx app can host sites", app=app.slug)
            app.kind = core.SITE_KIND
            if not await session.scalar(select(Site.id).where(Site.app_id == app.id,
                                                              Site.root == "")):  # fmt: skip
                now = self.clock.now()
                main = Site(app_id=app.id, slug="main", name=app.name, root="", port=None,
                            server_name=None, enabled=True, created_at=now)  # fmt: skip
                session.add(main)
                self.bus.publish("site.hosting_enabled", app=app.slug)
            await session.flush()
            return await self._view(session, app.id)

    # --- previews ---------------------------------------------------------------------

    async def plan_add(self, app_id: int, name: str, port: int, slug: str | None = None,
                       server_name: str | None = None) -> SitePlan:  # fmt: skip
        return await self._preview(app_id, self._adding(name, port, slug, server_name))

    async def plan_remove(self, app_id: int, site_id: int) -> SitePlan:
        return await self._preview(app_id, self._removing(site_id))

    async def plan_port(self, app_id: int, site_id: int, port: int) -> SitePlan:
        return await self._preview(app_id, self._moving(site_id, port))

    async def _preview(self, app_id: int, change: Change) -> SitePlan:
        """The change made, then dropped: the session is never committed (closing it
        rolls everything back), so nothing is written."""
        async with self.sessions() as session:
            await self._host(session, app_id, recreates=True)
            before = await self._ports(session, app_id)
            await change(session, app_id)
            await session.flush()
            after = await self._ports(session, app_id)
            if before == after:
                return SitePlan(False, None, "", before, after)
            upd = await self.revisions.plan_update(session, app_id, await _inputs(session, app_id))
            if conflicts := [conflict_dict(c) for c in upd.plan.conflicts]:
                raise PortConflictError("host ports already in use", conflicts=conflicts)
        return SitePlan(True, upd.number, upd.diff, before, after)

    # --- changes ------------------------------------------------------------------------

    async def add(self, app_id: int, name: str, port: int, slug: str | None = None,
                  server_name: str | None = None) -> tuple[int, Job, Job]:  # fmt: skip
        """The site's row, the revision publishing its port (job: recreate), then its
        nginx files (job: site_config). Returns the site's id and both jobs."""
        app, site, update, config, number = await self._republish(
            app_id, self._adding(name, port, slug, server_name)
        )
        self.bus.publish("site.added", app=app.slug, site=site.slug, port=site.port,
                         revision=number, job=update.id)  # fmt: skip
        return site.id, update, config

    async def change_port(self, app_id: int, site_id: int, port: int) -> tuple[Job, Job]:
        app, site, update, config, number = await self._republish(
            app_id, self._moving(site_id, port)
        )
        self.bus.publish("site.port_changed", app=app.slug, site=site.slug, port=port,
                         revision=number, job=update.id)  # fmt: skip
        return update, config

    async def remove(self, app_id: int, site_id: int, *, remove_data: bool = False) -> tuple[
        Job, Job
    ]:  # fmt: skip
        """nginx stops serving it first (no cut for the others), then the revision without
        its port recreates the container. Its files are kept unless remove_data."""
        app, site, update, config, number = await self._republish(
            app_id, self._removing(site_id), removal=True, remove_data=remove_data
        )
        self.bus.publish("site.removed", app=app.slug, site=site.slug, data_removed=remove_data,
                         revision=number, job=update.id)  # fmt: skip
        return config, update

    async def set_enabled(self, app_id: int, site_id: int, enabled: bool) -> Job:
        """Only nginx's files: the port stays published, nothing is recreated."""

        def edit(site: Site) -> None:
            site.enabled = enabled

        app, site, config = await self._reconfigure(app_id, site_id, edit)
        self.bus.publish("site.enabled" if enabled else "site.disabled", app=app.slug,
                         site=site.slug, job=config.id)  # fmt: skip
        return config

    async def set_server_name(self, app_id: int, site_id: int, server_name: str | None) -> Job:
        def edit(site: Site) -> None:
            if site.root == "":
                raise MainSiteError("the main site is served by any name", site=site.id)
            nginx.check(_nginx_site(site.slug, site.port, server_name))
            site.server_name = server_name

        app, site, config = await self._reconfigure(app_id, site_id, edit)
        self.bus.publish("site.server_name_changed", app=app.slug, site=site.slug,
                         server_name=server_name, job=config.id)  # fmt: skip
        return config

    # --- the two sequences every change goes through -----------------------------------

    async def _republish(
        self, app_id: int, change: Change, *, removal: bool = False, remove_data: bool = False
    ) -> tuple[Application, Site, Job, Job, int]:
        """A change that moves a port, in one transaction: the change, the revision that
        publishes the ports as they now are (its job recreates the container), and nginx's
        files (site_config). The files go after the revision, except for a removal: nginx
        stops serving the site first. Returns the app, the site, both jobs and the
        revision's number."""
        async with self.sessions() as session, session.begin():
            app = await self._host(session, app_id, recreates=True)
            site = await change(session, app_id)
            first = None
            if removal:
                folders = [site.root] if remove_data else []
                first = self._config(session, app.id, app.slug, remove_folders=folders)
            update, number = await self.revisions.queue_update(
                session, app_id, await _inputs(session, app_id)
            )
            config = first or self._config(session, app.id, app.slug)
        self.jobs.wake()
        return app, site, update, config, number

    async def _reconfigure(
        self, app_id: int, site_id: int, edit: Callable[[Site], None]
    ) -> tuple[Application, Site, Job]:
        """A change of nginx's files only (no port moves), in one transaction: the site's
        row edited, then the site_config job."""
        async with self.sessions() as session, session.begin():
            app = await self._host(session, app_id)
            site = await self._site(session, app_id, site_id)
            edit(site)
            config = self._config(session, app.id, app.slug)
        self.jobs.wake()
        return app, site, config

    # --- the changes themselves (run inside a transaction) ----------------------------

    def _adding(self, name: str, port: int, slug: str | None, server_name: str | None) -> Change:
        async def change(session: AsyncSession, app_id: int) -> Site:
            site_slug = slug or slugify(name)[:63]
            nginx.check(_nginx_site(site_slug, port, server_name))
            added = await session.scalar(
                select(func.count()).select_from(Site).where(Site.app_id == app_id, Site.root != "")
            )
            if (added or 0) >= MAX_SITES:
                raise TooManySitesError("too many sites on this nginx", limit=MAX_SITES)
            if await session.scalar(select(Site.id).where(Site.app_id == app_id,
                                                          Site.slug == site_slug)):  # fmt: skip
                raise SiteExistsError("a site with this name already exists", slug=site_slug)
            await self._free_port(session, app_id, port)
            site = Site(app_id=app_id, slug=site_slug, name=name.strip() or site_slug,
                        root=site_slug, port=port, server_name=server_name, enabled=True,
                        created_at=self.clock.now())  # fmt: skip
            session.add(site)
            await session.flush()
            return site

        return change

    def _moving(self, site_id: int, port: int) -> Change:
        async def change(session: AsyncSession, app_id: int) -> Site:
            site = await self._site(session, app_id, site_id)
            if site.root == "":
                raise MainSiteError("the main site uses the app's web port", site=site.id)
            nginx.check(_nginx_site(site.slug, port, site.server_name))
            if port != site.port:
                await self._free_port(session, app_id, port)
                site.port = port
            return site

        return change

    def _removing(self, site_id: int) -> Change:
        async def change(session: AsyncSession, app_id: int) -> Site:
            site = await self._site(session, app_id, site_id)
            if site.root == "":
                raise MainSiteError("the main site goes with its app", site=site.id)
            await session.delete(site)
            await session.flush()
            return site

        return change

    # --- helpers -----------------------------------------------------------------------

    async def _host(self, session: AsyncSession, app_id: int, *, recreates: bool = False
                    ) -> Application:  # fmt: skip
        app = await core.get_site(session, app_id)
        await core.conf_dir(session, app.id)  # 409 on an nginx still on template 1.0.0
        await core.sites_dir(session, app.id)
        if recreates and app.desired_state is DesiredState.STOPPED:
            # A revision's job always starts the container: start the app first.
            raise HostStoppedError("start this nginx before changing its sites' ports",
                                   app=app.slug)  # fmt: skip
        return app

    async def _site(self, session: AsyncSession, app_id: int, site_id: int) -> Site:
        site = await session.get(Site, site_id)
        if site is None or site.app_id != app_id:
            raise core.SiteNotFoundError(str(site_id))
        return site

    async def _ports(self, session: AsyncSession, app_id: int) -> list[int]:
        ports = await session.scalars(
            select(Site.port).where(Site.app_id == app_id, Site.root != "").order_by(Site.port)
        )
        return [p for p in ports if p is not None]

    async def _free_port(self, session: AsyncSession, app_id: int, port: int) -> None:
        """Ports the planner cannot see as such: another site of this nginx (a database
        rule), or one of the user's own extra ports in the advanced settings."""
        if other := await session.scalar(select(Site.slug).where(Site.app_id == app_id,
                                                                 Site.port == port)):  # fmt: skip
            raise _conflict(port, f"site {other}")
        latest = await latest_revision(session, app_id)
        own = Overrides.model_validate(latest.overrides or {}).of(core.SERVICE) if latest else None
        if own and any(port in (p.container, p.host) for p in own.ports):
            raise _conflict(port, "advanced settings")

    def _config(self, session: AsyncSession, app_id: int, slug: str, **params: Any) -> Job:
        return self.jobs.add(session, JobKind.SITE_CONFIG, app_id=app_id, app_slug=slug,
                             params={k: v for k, v in params.items() if v})  # fmt: skip


def _nginx_site(slug: str, port: int | None, server_name: str | None) -> nginx.NginxSite:
    return nginx.NginxSite(0, slug, slug, port, server_name, True)


def _conflict(port: int, used_by: str) -> PortConflictError:
    return PortConflictError("host ports already in use", conflicts=[
        {"port": port, "protocol": "tcp", "used_by": used_by, "suggestion": None}])  # fmt: skip


async def _inputs(session: AsyncSession, app_id: int) -> dict[str, Any]:
    """The app's current settings: a site change keeps them as they are."""
    latest = await latest_revision(session, app_id)
    return dict(latest.inputs) if latest else {}
