"""Zones: create, edit, delete. Assigning apps to zones belongs to the apps module."""

import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.core.clock import Clock
from hivora.core.errors import ConflictError, NotFoundError, ValidationError
from hivora.zones.models import NetworkMode, Zone

COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MODES = (NetworkMode.NONE, NetworkMode.SHARED)  # isolated/custom: not offered yet


class ZoneNotFoundError(NotFoundError):
    code = "zone_not_found"


class ZoneNotEmptyError(ConflictError):
    code = "zone_not_empty"


def zone_network(zone: Zone | None) -> str | None:
    """Docker network joined by the apps of a zone whose apps share one."""
    if zone is None or zone.network_mode is not NetworkMode.SHARED:
        return None
    return f"hivora-zone-{zone.slug}"


def _slug(name: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:50].strip("-") or "zone"


def _check(name: str, color: str, mode: NetworkMode) -> None:
    if not 1 <= len(name.strip()) <= 100:
        raise ValidationError("invalid zone name", field="name")
    if not COLOR.match(color):
        raise ValidationError("invalid colour", field="color")
    if mode not in MODES:
        raise ValidationError("unsupported network mode", field="network_mode")


async def find_zone(session: AsyncSession, slug: str) -> Zone | None:
    """The zone with this slug, or None (no error: the caller decides)."""
    zone: Zone | None = await session.scalar(select(Zone).where(Zone.slug == slug))
    return zone


async def get_zone(session: AsyncSession, slug: str) -> Zone:
    zone = await session.scalar(select(Zone).where(Zone.slug == slug))
    if zone is None:
        raise ZoneNotFoundError(slug)
    return zone


async def list_zones(session: AsyncSession) -> list[Zone]:
    return list(await session.scalars(select(Zone).order_by(Zone.sort_order, Zone.name)))


async def create_zone(
    session: AsyncSession, clock: Clock, name: str, color: str, mode: NetworkMode
) -> Zone:
    _check(name, color, mode)
    base = slug = _slug(name)
    n = 2
    while await session.scalar(select(Zone.id).where(Zone.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    order = (await session.scalar(select(func.max(Zone.sort_order)))) or 0
    zone = Zone(slug=slug, name=name.strip(), color=color, icon=None, description="",
                network_mode=mode, sort_order=order + 1, is_system=False,
                created_at=clock.now())  # fmt: skip
    session.add(zone)
    await session.flush()
    return zone


async def edit_zone(
    session: AsyncSession, slug: str, name: str, color: str, mode: NetworkMode
) -> tuple[Zone, bool]:
    """Returns the zone and whether its network changed (its apps must be redeployed)."""
    _check(name, color, mode)
    zone = await get_zone(session, slug)
    changed = zone.network_mode is not mode
    zone.name, zone.color, zone.network_mode = name.strip(), color, mode
    return zone, changed


async def delete_zone(session: AsyncSession, slug: str, apps_in_zone: int) -> Zone:
    zone = await get_zone(session, slug)
    if zone.is_system:
        raise ConflictError("a system zone cannot be deleted", slug=slug)
    if apps_in_zone:
        raise ZoneNotEmptyError("move its applications first", slug=slug, apps=apps_in_zone)
    await session.delete(zone)
    return zone
