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
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import PortConflictError, conflict_dict, get_app, slugify
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
from hivora.sites.port_check import PortCheck
from hivora.sites.views import HostedSite, SiteHost, SitePlan, host_view, site_view
from hivora.state import StateStore


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


Change = Callable[[AsyncSession, int], Awaitable[Site]]  # one change to a host's sites
# Inputs of the app a change also sets, filled while it runs (the main site's port is the
# app's web port: moving it changes that input).
Patch = dict[str, Any]


class SiteHosting:
    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], revisions: Revisions,
        jobs: JobQueue, bus: EventBus, clock: Clock, settings: Settings, state: StateStore,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.revisions = revisions
        self.ports = PortCheck(state)
        self.jobs = jobs
        self.bus = bus
        self.clock = clock
        self.settings = settings

    # --- reading, and turning an nginx into a host ---------------------------------

    async def view(self, app_id: int) -> SiteHost:
        """A host and its sites, the main one first (404 for an app that hosts none)."""
        async with self.sessions() as session:
            return await host_view(session, app_id, self.settings.host_lan_ip)

    async def site(self, app_id: int, site_id: int) -> HostedSite:
        """One site, as ``view`` lists it."""
        async with self.sessions() as session:
            return await site_view(session, app_id, site_id, self.settings.host_lan_ip)

    async def enable_hosting(self, app_id: int) -> SiteHost:
        """An nginx deployed from the catalog becomes a host: its html volume is its main
        site. Nothing is redeployed; a host already is one (no change)."""
        async with self.sessions() as session, session.begin():
            app = await get_app(session, app_id)
            if await template_slug(session, app) != "nginx":
                raise NotNginxError("only an nginx app can host sites", app=app.slug)
            app.mark_hosting()
            if not await session.scalar(select(Site.id).where(Site.app_id == app.id,
                                                              Site.root == "")):  # fmt: skip
                now = self.clock.now()
                main = Site(app_id=app.id, slug="main", name=app.name, root="", port=None,
                            server_name=None, enabled=True, created_at=now)  # fmt: skip
                session.add(main)
                self.bus.publish("site.hosting_enabled", app=app.slug)
            await session.flush()
            return await host_view(session, app.id, self.settings.host_lan_ip)

    # --- previews ---------------------------------------------------------------------

    async def plan_add(self, app_id: int, name: str, port: int, slug: str | None = None,
                       server_name: str | None = None) -> SitePlan:  # fmt: skip
        return await self._preview(app_id, self._adding(name, port, slug, server_name))

    async def plan_remove(self, app_id: int, site_id: int) -> SitePlan:
        return await self._preview(app_id, self._removing(site_id))

    async def plan_port(self, app_id: int, site_id: int, port: int) -> SitePlan:
        patch: Patch = {}
        return await self._preview(app_id, self._moving(site_id, port, patch), patch)

    async def _preview(self, app_id: int, change: Change, patch: Patch | None = None) -> SitePlan:
        """The change made, then dropped: the session is never committed (closing it
        rolls everything back), so nothing is written."""
        async with self.sessions() as session:
            await self._host(session, app_id, recreates=True)
            before = await core.added_ports(session, app_id)
            await change(session, app_id)
            await session.flush()
            after = await core.added_ports(session, app_id)
            if before == after and not patch:
                return SitePlan(False, None, "", before, after)
            inputs = {**await core.current_inputs(session, app_id), **(patch or {})}
            upd = await self.revisions.plan_update(session, app_id, inputs)
            if conflicts := [conflict_dict(c) for c in upd.plan.conflicts]:
                raise await self.ports.conflict(session, app_id, conflicts, before)
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
        """Any site's, the main one's included (the app's web port: a new revision too)."""
        patch: Patch = {}
        app, site, update, config, number = await self._republish(
            app_id, self._moving(site_id, port, patch), patch=patch
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
        self, app_id: int, change: Change, *, removal: bool = False, remove_data: bool = False,
        patch: Patch | None = None,
    ) -> tuple[Application, Site, Job, Job, int]:  # fmt: skip
        """A change that moves a port, in one transaction: the change, the revision that
        publishes the ports as they now are (its job recreates the container), and nginx's
        files (site_config). The files go after the revision, except for a removal: nginx
        stops serving the site first. Returns the app, the site, both jobs and the
        revision's number."""
        async with self.sessions() as session, session.begin():
            app = await self._host(session, app_id, recreates=True)
            before = await core.added_ports(session, app_id)
            site = await change(session, app_id)
            first = None
            if removal:
                folders = [site.root] if remove_data else []
                first = self._config(session, app.id, app.slug, remove_folders=folders)
            try:
                inputs = {**await core.current_inputs(session, app_id), **(patch or {})}
                update, number = await self.revisions.queue_update(session, app_id, inputs)
            except PortConflictError as err:
                conflicts = cast(list[dict[str, Any]], err.details["conflicts"])
                raise await self.ports.conflict(session, app_id, conflicts, before) from None
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
            if (added or 0) >= core.MAX_SITES:
                raise TooManySitesError("too many sites on this nginx", limit=core.MAX_SITES)
            if await session.scalar(select(Site.id).where(Site.app_id == app_id,
                                                          Site.slug == site_slug)):  # fmt: skip
                raise SiteExistsError("a site with this name already exists", slug=site_slug)
            await self.ports.free(session, app_id, port)
            site = Site(app_id=app_id, slug=site_slug, name=name.strip() or site_slug,
                        root=site_slug, port=port, server_name=server_name, enabled=True,
                        created_at=self.clock.now())  # fmt: skip
            session.add(site)
            await session.flush()
            return site

        return change

    def _moving(self, site_id: int, port: int, patch: Patch) -> Change:
        async def change(session: AsyncSession, app_id: int) -> Site:
            site = await self._site(session, app_id, site_id)
            if site.root == "":  # the main site: its port is the app's web port (an input)
                if port != (await core.current_inputs(session, app_id)).get("web_port"):
                    await self.ports.free(session, app_id, port)
                    patch["web_port"] = port
                return site
            nginx.check(_nginx_site(site.slug, port, site.server_name))
            if port != site.port:
                await self.ports.free(session, app_id, port)
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
        dirs = await core.host_dirs(session, app.id)
        dirs.conf()  # 409 on an nginx still on template 1.0.0
        dirs.sites()
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

    def _config(self, session: AsyncSession, app_id: int, slug: str, **params: Any) -> Job:
        return self.jobs.add(session, JobKind.SITE_CONFIG, app_id=app_id, app_slug=slug,
                             params={k: v for k, v in params.items() if v})  # fmt: skip


def _nginx_site(slug: str, port: int | None, server_name: str | None) -> nginx.NginxSite:
    return nginx.NginxSite(0, slug, slug, port, server_name, True)
