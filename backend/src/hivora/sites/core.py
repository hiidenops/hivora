"""What the sites' sub-modules share: what a site is, where its files are, and the
leftovers of its work files.

Work files (uploads, staging folders) live next to the ``html`` folder: same filesystem
(moved in by ``rename``) and outside the bind mount (never served).
"""

import shutil
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from hivora.apps.models import Application, Service
from hivora.core.errors import ConflictError, NotFoundError

SITE_KIND = "static-site"
HTML_TARGET = "/usr/share/nginx/html"  # the nginx template's "html" volume
UPLOAD_TTL_S = 24 * 3600  # an upload left by an interrupted job is swept after this
_STAGED = (".hivora-upload-", ".hivora-edit-")  # files a queued job may still be waiting for


class SiteNotFoundError(NotFoundError):
    code = "site_not_found"


async def get_site(session: AsyncSession, app_id: int) -> Application:
    app = await session.get(Application, app_id)
    if app is None or app.kind != SITE_KIND:
        raise SiteNotFoundError(str(app_id))
    return app


async def html_dir(session: AsyncSession, app_id: int) -> Path:
    service = await session.scalar(
        select(Service).where(Service.app_id == app_id).options(selectinload(Service.volumes))
    )
    for volume in service.volumes if service else []:
        if volume.target == HTML_TARGET:
            return Path(volume.source)
    raise ConflictError("site has no html volume", app=app_id)


async def deployed_html(
    sessions: async_sessionmaker[AsyncSession], app_id: int
) -> tuple[Application, Path]:
    async with sessions() as session:
        app = await get_site(session, app_id)
        if app.current_revision_id is None:
            raise ConflictError("site not deployed", slug=app.slug)
        return app, await html_dir(session, app.id)


def sweep(app_dir: Path, keep: Path) -> None:
    """Leftovers of an interrupted job: staging folders, and uploads or staged edits old
    enough that no queued job can still be waiting for them (the lane runs one job at a
    time)."""
    for stale in app_dir.glob(".hivora-*"):
        if stale == keep:
            continue
        if stale.name.startswith(".hivora-staging-") and stale.is_dir() and not stale.is_symlink():
            shutil.rmtree(stale)
        elif stale.name.startswith(_STAGED) and (
            time.time() - stale.lstat().st_mtime > UPLOAD_TTL_S
        ):
            stale.unlink()
