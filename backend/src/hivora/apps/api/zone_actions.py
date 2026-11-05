"""A zone's start order and its actions (/api/v1/zones/{slug}/...): the apps of a zone
started, stopped or restarted in the order of their dependencies."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.apps.api.common import JobRef, job_ref
from hivora.apps.zone_actions import Startup
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["zones"])


class DependencyIO(BaseModel):
    app: int  # starts after
    after: int


class StartupApp(BaseModel):
    id: int
    slug: str
    name: str
    status: str


class StartupOut(BaseModel):
    zone: str
    timeout_s: int
    apps: list[StartupApp]
    dependencies: list[DependencyIO]
    steps: list[list[int]]  # app ids, step by step (stopping: backwards)


class StartupIn(BaseModel):
    dependencies: list[DependencyIO] = Field(max_length=500)
    timeout_s: int = Field(default=120, ge=10, le=3600)


class ZoneActionIn(BaseModel):
    action: Literal["start", "stop", "restart"]


def startup_out(s: Startup) -> StartupOut:
    return StartupOut(
        zone=s.zone, timeout_s=s.timeout_s, steps=s.steps,
        apps=[StartupApp(id=a.id, slug=a.slug, name=a.name, status=a.status) for a in s.apps],
        dependencies=[DependencyIO(app=a, after=d) for a, d in s.dependencies],
    )  # fmt: skip


@router.get("/{slug}/startup")
async def get_startup(slug: str, _: Viewer, rt: RuntimeDep) -> StartupOut:
    """The zone's apps, the dependencies between them, the start order and the timeout."""
    return startup_out(await rt.zone_actions.startup(slug))


@router.put("/{slug}/startup")
async def put_startup(slug: str, body: StartupIn, _: Operator, rt: RuntimeDep) -> StartupOut:
    """Replace the zone's dependencies (same zone, no loop) and its start timeout."""
    deps = [(d.app, d.after) for d in body.dependencies]
    return startup_out(await rt.zone_actions.set_startup(slug, deps, body.timeout_s))


@router.post("/{slug}/actions", status_code=202)
async def zone_action(slug: str, body: ZoneActionIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """Start, stop or restart the zone's apps in their order (one job; one at a time)."""
    return job_ref(await rt.zone_actions.request(slug, body.action))


class PurgeAppOut(BaseModel):
    id: int
    name: str
    containers: list[str]
    files: list[str]  # compose.yaml, .env: always removed
    data: list[str]  # bind-mounted data: removed only on request


class PurgePlanOut(BaseModel):
    zone: str
    name: str
    system: bool  # Administration: never removed
    apps: list[PurgeAppOut]
    blocked: list[str]  # apps of other zones linked to apps of this one
    vpn: str | None  # a VPN of another zone that serves it: the zone is unlinked from it


class PurgeIn(BaseModel):
    remove_data: bool = False


async def _outside_vpn(rt: RuntimeDep, slug: str) -> tuple[int, str] | None:
    """The VPN that serves the zone from outside it: (its app id, its name)."""
    from hivora.apps.queries import app_id_by_slug
    from hivora.zones import get_zone

    async with rt.sessions() as session:
        vpn = (await rt.apps.planner.vpn_zones(session)).get(slug)
        if vpn is None:
            return None
        zone = await get_zone(session, slug)
        app_id = await app_id_by_slug(session, vpn[0])
        app = await rt.apps.get(session, app_id) if app_id else None
    return (app.id, vpn[1]) if app is not None and app.zone_id != zone.id else None


@router.get("/{slug}/purge")
async def purge_plan(slug: str, _: Operator, rt: RuntimeDep) -> PurgePlanOut:
    """What removing the zone and everything in it removes (shown before)."""
    vpn = await _outside_vpn(rt, slug)
    return PurgePlanOut(**await rt.zone_actions.purge_plan(slug), vpn=vpn[1] if vpn else None)


@router.post("/{slug}/purge", status_code=202)
async def purge(slug: str, body: PurgeIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """Remove every app of the zone (data kept unless asked), then the zone (one job)."""
    if vpn := await _outside_vpn(rt, slug):  # its VPN stops serving it first
        current = (await rt.vpn.overview(vpn[0]))["zones"]
        await rt.vpn.set_zones(vpn[0], [z for z in current if z != slug])
    return job_ref(await rt.zone_actions.purge(slug, remove_data=body.remove_data))
