"""Read-only queries behind the app read routes (`apps/api/queries.py`): no state, the
caller's session is used, so a route keeps all its reads in one session."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.models import Application, AppRevision
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
