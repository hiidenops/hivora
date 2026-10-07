"""What a host shows: its sites (the main one first, each with its address), whether it
needs an update or a start, and whether nginx serves them as recorded (its last
site_config job). Read only, in the caller's session."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.models import DesiredState
from hivora.jobs import JobKind
from hivora.jobs.queries import last_job
from hivora.sites import core
from hivora.sites.models import Site


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
class ConfigState:
    """The host's last site_config job: whether nginx serves the sites as recorded."""

    job_id: int
    status: str  # queued, running, succeeded, failed, cancelled
    error: str | None


@dataclass(frozen=True, slots=True)
class SiteHost:
    app_id: int
    slug: str
    name: str
    upgrade_required: bool  # nginx still on template 1.0.0: only its main site
    stopped: bool  # port changes are refused until it is started
    max_sites: int
    sites: list[HostedSite]
    config: ConfigState | None  # None: no configuration applied yet


@dataclass(frozen=True, slots=True)
class SitePlan:
    recreate: bool  # the container is recreated: every site of this nginx stops ~1 s
    revision: int | None  # the revision this change makes (None: no new revision)
    diff: str
    ports_before: list[int]
    ports_after: list[int]


async def host_view(session: AsyncSession, app_id: int, lan: str | None) -> SiteHost:
    """A host and its sites, the main one first (404 for an app that hosts none).
    ``lan``: the host's LAN address, for the sites' URLs."""
    app = await core.get_site(session, app_id)
    try:
        await core.conf_dir(session, app.id)
        upgrade_required = False
    except core.HostUpgradeRequiredError:
        upgrade_required = True
    rows = await session.scalars(
        select(Site).where(Site.app_id == app.id).order_by(Site.root != "", Site.id)
    )
    web_port = (await core.current_inputs(session, app.id)).get("web_port")
    sites = []
    main_port = int(web_port) if web_port is not None else None
    for r in rows:
        port = main_port if r.root == "" else r.port
        url = f"http://{lan}:{port}" if lan and port else None
        sites.append(HostedSite(r.id, r.slug, r.name, r.root == "", port, r.server_name,
                                r.enabled, url))  # fmt: skip
    last = await last_job(session, app.id, JobKind.SITE_CONFIG)
    config = ConfigState(last.id, last.status.value, last.error) if last else None
    return SiteHost(app.id, app.slug, app.name, upgrade_required,
                    app.desired_state is DesiredState.STOPPED, core.MAX_SITES, sites,
                    config)  # fmt: skip
