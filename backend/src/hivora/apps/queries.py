"""Read-only queries behind the app read routes (`apps/api/queries.py`): no state, the
caller's session is used, so a route keeps all its reads in one session."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from hivora.apps.models import HOSTING_KIND, Application, AppRevision, Service
from hivora.core.errors import NotFoundError
from hivora.templates.models import TemplateVersion


async def apps_with_template(session: AsyncSession) -> list[tuple[Application, str | None]]:
    """Every app with its template slug (None: adopted, no template), by name."""
    rows = await session.execute(
        select(Application, TemplateVersion.slug)
        .outerjoin(TemplateVersion, Application.template_version_id == TemplateVersion.id)
        .order_by(Application.name)
    )
    return [(app, template) for app, template in rows]


async def template_slug(session: AsyncSession, app: Application) -> str | None:
    slug: str | None = await session.scalar(
        select(TemplateVersion.slug).where(TemplateVersion.id == app.template_version_id)
    )
    return slug


async def applied_revision_number(session: AsyncSession, app: Application) -> int | None:
    revision = (await session.get(AppRevision, app.current_revision_id)
                if app.current_revision_id else None)  # fmt: skip
    return revision.number if revision else None


async def applied_compose(session: AsyncSession, app: Application) -> str:
    """The compose of the applied revision, else of the latest one."""
    revision_id = app.current_revision_id or await session.scalar(
        select(AppRevision.id).where(AppRevision.app_id == app.id)
        .order_by(AppRevision.number.desc())
    )  # fmt: skip
    if revision_id is None:
        raise NotFoundError("no revision")
    revision = await session.get_one(AppRevision, revision_id)
    return revision.compose_yaml


async def revisions_of(session: AsyncSession, app_id: int) -> list[AppRevision]:
    """The app's revisions, newest first."""
    rows = await session.scalars(
        select(AppRevision).where(AppRevision.app_id == app_id)
        .order_by(AppRevision.number.desc())
    )  # fmt: skip
    return list(rows)


# --- for the sites (an nginx that hosts sites) -----------------------------------------


async def hosting_app(session: AsyncSession, app_id: int) -> Application | None:
    """The app if it hosts sites (``application.kind``), else None."""
    app = await session.get(Application, app_id)
    return app if app is not None and app.kind == HOSTING_KIND else None


async def app_id_by_slug(session: AsyncSession, slug: str) -> int | None:
    """The id of the app with this slug, if any."""
    app_id: int | None = await session.scalar(
        select(Application.id).where(Application.slug == slug)
    )
    return app_id


async def hosting_app_id(session: AsyncSession, slug: str) -> int | None:
    """The id of the app with this slug if it hosts sites, else None."""
    app_id: int | None = await session.scalar(
        select(Application.id).where(Application.slug == slug, Application.kind == HOSTING_KIND)
    )
    return app_id


async def volume_sources(session: AsyncSession, app_id: int) -> dict[str, Path]:
    """The host folders bound in the app's (first) service, by target, in one query."""
    service = await session.scalar(
        select(Service).where(Service.app_id == app_id).options(selectinload(Service.volumes))
    )
    return {v.target: Path(v.source) for v in service.volumes} if service else {}
