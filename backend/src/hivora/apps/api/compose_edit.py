"""Hand-written compose routes (admin)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.apps.api.common import ConflictOut, JobRef, job_ref
from hivora.web.deps import Admin, RuntimeDep

router = APIRouter()


class ComposeIn(BaseModel):
    compose_yaml: str = Field(min_length=1, max_length=200_000)


class ComposePlanOut(BaseModel):
    diff: str
    problems: list[str]  # why it cannot be applied (empty: it can)
    conflicts: list[ConflictOut]


@router.post("/{app_id}/compose/plan")
async def plan_compose(app_id: int, body: ComposeIn, _: Admin, rt: RuntimeDep) -> ComposePlanOut:
    """Check a hand-written compose file (resolved by Compose, then security checks)."""
    async with rt.sessions() as session:
        p = await rt.apps.compose.plan(session, app_id, body.compose_yaml)
    conflicts = [ConflictOut(port=c.port, protocol=c.protocol, used_by=c.used_by,
                             suggestion=c.suggestion) for c in p.conflicts]  # fmt: skip
    return ComposePlanOut(diff=p.diff, problems=p.problems, conflicts=conflicts)


@router.put("/{app_id}/compose", status_code=202)
async def apply_compose(app_id: int, body: ComposeIn, _: Admin, rt: RuntimeDep) -> JobRef:
    """Apply a hand-written compose file as a new revision (admin: it runs as written)."""
    return job_ref(await rt.apps.compose.apply(app_id, body.compose_yaml))
