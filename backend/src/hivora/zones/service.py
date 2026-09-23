"""Zone lookups. Assigning apps to zones belongs to the apps module."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.core.errors import NotFoundError
from hivora.zones.models import Zone


class ZoneNotFoundError(NotFoundError):
    code = "zone_not_found"


async def get_zone(session: AsyncSession, slug: str) -> Zone:
    zone = await session.scalar(select(Zone).where(Zone.slug == slug))
    if zone is None:
        raise ZoneNotFoundError(slug)
    return zone


async def list_zones(session: AsyncSession) -> list[Zone]:
    return list(await session.scalars(select(Zone).order_by(Zone.sort_order, Zone.name)))
