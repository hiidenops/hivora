"""The ports an nginx host publishes for its added sites, from the database.

Given to the apps' planner by the composition root: every compile of a host (update,
upgrade, restore) then publishes its sites as they are now, without storing them in the
revision's advanced settings. One port per added site, the same inside and outside the
container; a site turned off keeps its port (turning it on again recreates nothing).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.models import Application
from hivora.sites.core import SERVICE, SITE_KIND
from hivora.sites.models import Site
from hivora.templates.overrides import ExtraPort, Overrides

MAIN_PORT_KEY = "80/tcp"  # the main site's port, whose exposure the sites follow


async def site_ports(session: AsyncSession, slug: str, overrides: Overrides) -> list[ExtraPort]:
    main = overrides.of(SERVICE)
    exposure = main.publish.get(MAIN_PORT_KEY, "lan") if main else "lan"
    if exposure == "none":  # the main site is not published: neither are the others
        return []
    ports = await session.scalars(
        select(Site.port)
        .join(Application, Application.id == Site.app_id)
        .where(Application.slug == slug, Application.kind == SITE_KIND, Site.root != "")
        .order_by(Site.id)
    )
    return [ExtraPort(container=p, host=p, protocol="tcp", exposure=exposure)
            for p in ports if p is not None]  # fmt: skip
