"""Zone routes (/api/v1/zones)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.web.deps import Operator, RuntimeDep, Viewer
from hivora.zones.models import NetworkMode, Zone
from hivora.zones.service import create_zone, delete_zone, edit_zone, find_zone, list_zones

router = APIRouter(tags=["zones"])


class ZoneOut(BaseModel):
    id: int
    slug: str
    name: str
    color: str
    icon: str | None
    network_mode: NetworkMode
    is_system: bool
    apps: int  # applications in the zone


class ZoneIn(BaseModel):
    name: str = Field(max_length=100)
    color: str = Field(max_length=7)
    network_mode: NetworkMode = NetworkMode.NONE


def _out(z: Zone, apps: int) -> ZoneOut:
    return ZoneOut(id=z.id, slug=z.slug, name=z.name, color=z.color, icon=z.icon,
                   network_mode=z.network_mode, is_system=z.is_system, apps=apps)  # fmt: skip


@router.get("")
async def zones(_: Viewer, rt: RuntimeDep) -> list[ZoneOut]:
    async with rt.sessions() as session:
        counts = await rt.apps.apps_per_zone(session)
        return [_out(z, counts.get(z.id, 0)) for z in await list_zones(session)]


@router.post("", status_code=201)
async def create(body: ZoneIn, _: Operator, rt: RuntimeDep) -> ZoneOut:
    async with rt.sessions() as session, session.begin():
        zone = await create_zone(session, rt.clock, body.name, body.color, body.network_mode)
        out = _out(zone, 0)
    rt.bus.publish("zone.created", target=out.slug, network_mode=out.network_mode.value)
    return out


@router.put("/{slug}")
async def edit(slug: str, body: ZoneIn, _: Operator, rt: RuntimeDep) -> ZoneOut:
    """A network change redeploys the zone's apps (one job each)."""
    async with rt.sessions() as session, session.begin():
        zone, changed = await edit_zone(session, slug, body.name, body.color, body.network_mode)
        out = _out(zone, (await rt.apps.apps_per_zone(session)).get(zone.id, 0))
    if changed:
        await rt.apps.redeploy_zone(out.id)
    rt.bus.publish("zone.updated", target=slug, network_changed=changed)
    return out


@router.delete("/{slug}", status_code=204)
async def delete(slug: str, _: Operator, rt: RuntimeDep) -> None:
    async with rt.sessions() as session, session.begin():
        zone = await find_zone(session, slug)
        apps = (await rt.apps.apps_per_zone(session)).get(zone.id, 0) if zone else 0
        await delete_zone(session, slug, apps)
    await rt.gateway.remove_network(f"hivora-zone-{slug}")
    rt.bus.publish("zone.deleted", target=slug)
