"""Lifecycle routes: start / stop / restart, and removal.

Two routers: in the public route order, the zone move (a revisions route) sits between
the actions and the removal routes, and that order is kept.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from hivora.apps.api.common import JobRef, job_ref
from hivora.web.deps import Operator, RuntimeDep

router = APIRouter()
removal_router = APIRouter()


class RemovalPlanOut(BaseModel):
    slug: str
    containers: list[str]
    files: list[str]
    data: list[str]


@router.post("/{app_id}/start", status_code=202)
async def start(app_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await rt.apps.start(app_id))


@router.post("/{app_id}/stop", status_code=202)
async def stop(app_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await rt.apps.stop(app_id))


@router.post("/{app_id}/restart", status_code=202)
async def restart(app_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await rt.apps.restart(app_id))


@removal_router.get("/{app_id}/removal-plan")
async def removal_plan(app_id: int, _: Operator, rt: RuntimeDep) -> RemovalPlanOut:
    p = await rt.apps.removal_plan(app_id)
    return RemovalPlanOut(slug=p.slug, containers=p.containers, files=p.files, data=p.data)


@removal_router.delete("/{app_id}", status_code=202)
async def remove(app_id: int, _: Operator, rt: RuntimeDep, remove_data: bool = False) -> JobRef:
    """Data is kept unless ``remove_data=true`` is passed explicitly."""
    return job_ref(await rt.apps.remove(app_id, remove_data=remove_data))
