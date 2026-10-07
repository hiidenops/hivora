"""What the sites' sub-modules share: what a site is, where its files are, and the
leftovers of its work files.

Work files (uploads, staging folders) live next to the ``html`` folder: same filesystem
(moved in by ``rename``) and outside the bind mount (never served).
"""

import shutil
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import latest_revision
from hivora.apps.models import HOSTING_KIND, Application
from hivora.apps.queries import hosting_app, volume_source
from hivora.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from hivora.sites.models import Site
from hivora.sites.nginx import NginxSite

SITE_KIND = HOSTING_KIND
SERVICE = "server"  # the nginx template's main service
MAX_SITES = 30  # added sites per host (the main site aside)
HTML_TARGET = "/usr/share/nginx/html"  # the nginx template's "html" volume
CONF_TARGET = "/etc/nginx/hivora.d"  # its "conf" volume (template 1.1.0 and later)
SITES_TARGET = "/usr/share/nginx/sites"  # its "sites" volume: one folder per added site
UPLOAD_TTL_S = 24 * 3600  # an upload left by an interrupted job is swept after this
_STAGED = (".hivora-upload-", ".hivora-edit-")  # files a queued job may still be waiting for
_WORK_DIRS = (".hivora-staging-", ".hivora-conf-")  # folders of one running job only


class SiteNotFoundError(NotFoundError):
    code = "site_not_found"


class HostUpgradeRequiredError(ConflictError):
    code = "host_upgrade_required"


async def get_site(session: AsyncSession, app_id: int) -> Application:
    if (app := await hosting_app(session, app_id)) is None:
        raise SiteNotFoundError(str(app_id))
    return app


async def current_inputs(session: AsyncSession, app_id: int) -> dict[str, Any]:
    """The app's current settings: a site change keeps them as they are."""
    latest = await latest_revision(session, app_id)
    return dict(latest.inputs) if latest else {}


async def added_ports(session: AsyncSession, app_id: int) -> list[int]:
    """The ports of the host's added sites, in order."""
    ports = await session.scalars(
        select(Site.port).where(Site.app_id == app_id, Site.root != "").order_by(Site.port)
    )
    return [p for p in ports if p is not None]


async def html_dir(session: AsyncSession, app_id: int) -> Path:
    if (path := await volume_source(session, app_id, HTML_TARGET)) is None:
        raise ConflictError("site has no html volume", app=app_id)
    return path


async def conf_dir(session: AsyncSession, app_id: int) -> Path:
    """The folder of the nginx files Hivora writes; only nginx 1.1.0 and later has it."""
    if (path := await volume_source(session, app_id, CONF_TARGET)) is None:
        raise HostUpgradeRequiredError("update this nginx to host several sites", app=app_id)
    return path


async def sites_dir(session: AsyncSession, app_id: int) -> Path:
    if (path := await volume_source(session, app_id, SITES_TARGET)) is None:
        raise HostUpgradeRequiredError("update this nginx to host several sites", app=app_id)
    return path


async def site_root(session: AsyncSession, app_id: int, site_id: int | None) -> tuple[Path, Path]:
    """The folder of one site's files, and the app's folder (where work files go: same
    filesystem, outside the mounts). None, or the main site's id: the html volume, as
    before any site row existed. An added site: its folder in the sites volume, which
    must not be a link (it could lead into another site)."""
    html = await html_dir(session, app_id)
    if site_id is None:
        return html, html.parent
    site = await session.get(Site, site_id)
    if site is None or site.app_id != app_id:
        raise SiteNotFoundError(str(site_id))
    if site.root == "":
        return html, html.parent
    folder = await sites_dir(session, app_id) / site.root
    if folder.is_symlink():
        raise PermissionDeniedError("a site's folder cannot be a link", site=site.slug)
    return folder, html.parent


async def deployed_root(
    sessions: async_sessionmaker[AsyncSession], app_id: int, site_id: int | None
) -> tuple[Application, Path, Path]:
    """A deployed host, and one of its sites: the app, the site's folder, the app's."""
    async with sessions() as session:
        app = await get_site(session, app_id)
        if app.current_revision_id is None:
            raise ConflictError("site not deployed", slug=app.slug)
        folder, work = await site_root(session, app.id, site_id)
        return app, folder, work


async def sites_of(session: AsyncSession, app_id: int) -> list[NginxSite]:
    rows = await session.scalars(select(Site).where(Site.app_id == app_id).order_by(Site.id))
    return [NginxSite(r.id, r.slug, r.root, r.port, r.server_name, r.enabled) for r in rows]


def sweep(app_dir: Path, keep: Path) -> None:
    """Leftovers of an interrupted job: staging folders, and uploads or staged edits old
    enough that no queued job can still be waiting for them (the lane runs one job at a
    time)."""
    for stale in app_dir.glob(".hivora-*"):
        if stale == keep:
            continue
        if stale.name.startswith(_WORK_DIRS) and stale.is_dir() and not stale.is_symlink():
            shutil.rmtree(stale)
        elif stale.name.startswith(_STAGED) and (
            time.time() - stale.lstat().st_mtime > UPLOAD_TTL_S
        ):
            stale.unlink()
