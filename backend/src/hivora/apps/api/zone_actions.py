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
