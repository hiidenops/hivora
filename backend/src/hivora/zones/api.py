"""Zone routes (/api/v1/zones)."""

from fastapi import APIRouter
from pydantic import BaseModel

from hivora.web.deps import RuntimeDep, Viewer
from hivora.zones.models import NetworkMode
from hivora.zones.service import list_zones

router = APIRouter(tags=["zones"])


class ZoneOut(BaseModel):
    id: int
    slug: str
    name: str
    color: str
    icon: str | None
    network_mode: NetworkMode
    is_system: bool


@router.get("")
async def zones(_: Viewer, rt: RuntimeDep) -> list[ZoneOut]:
    async with rt.sessions() as session:
        return [ZoneOut(id=z.id, slug=z.slug, name=z.name, color=z.color, icon=z.icon,
                        network_mode=z.network_mode, is_system=z.is_system)
                for z in await list_zones(session)]  # fmt: skip
