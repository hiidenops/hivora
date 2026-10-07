"""Adoption routes: compose stacks already running on this Docker."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.web.deps import Operator, RuntimeDep

router = APIRouter()


class CandidateOut(BaseModel):
    project: str  # its compose project name, the app id once adopted
    services: list[str]
    running: int
    containers: int
    working_dir: str | None  # where its compose file lives on the host


class AdoptIn(BaseModel):
    project: str = Field(min_length=1, max_length=63)
    name: str = Field(default="", max_length=100)
    zone: str | None = None


@router.get("/discover")
async def discover(_: Operator, rt: RuntimeDep) -> list[CandidateOut]:
    """Compose stacks running on this Docker that Hivora does not manage yet."""
    return [CandidateOut(project=c.project, services=c.services, running=c.running,
                         containers=c.containers, working_dir=c.working_dir)
            for c in rt.apps.adoption.candidates()]  # fmt: skip


@router.post("/adopt", status_code=201)
async def adopt(body: AdoptIn, _: Operator, rt: RuntimeDep) -> dict[str, int]:
    """Manage a running stack from Hivora: metadata only, nothing is redeployed."""
    app = await rt.apps.adoption.adopt(body.project, body.name.strip(), body.zone)
    return {"id": app.id}
