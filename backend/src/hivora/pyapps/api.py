"""Python project routes, mounted under /api/v1/apps."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from hivora.apps.api import DeployOut, JobRef, app_out, job_ref
from hivora.pyapps.analyze import Mount
from hivora.pyapps.service import ProjectSpec, PythonProjects
from hivora.web.deps import Operator, RuntimeDep

router = APIRouter(tags=["python"])


class MountIO(BaseModel):
    source: str = Field(max_length=200)  # folder in the project ("" = all of it)
    target: str = Field(max_length=200)  # path in the container
    data: bool = False  # kept when new code is sent


class EnvIO(BaseModel):
    key: str = Field(max_length=128)
    value: str = Field(default="", max_length=4096)
    secret: bool = False
    source: str = ""


class PortIO(BaseModel):
    container: int = Field(ge=1, le=65535)
    host: int = Field(ge=1, le=65535)


class AnalysisOut(BaseModel):
    token: str  # the uploaded archive, to deploy it (kept an hour)
    name: str
    python: str
    requirements: str | None
    workdir: str
    entry: list[str]
    mounts: list[MountIO]
    env: list[EnvIO]
    ports: list[int]
    apt: list[str]
    notes: list[str]  # what the analysis relied on
    files: int
    size: int


class ProjectIn(BaseModel):
    token: str = Field(max_length=64)
    name: str = Field(min_length=1, max_length=100)
    zone: str | None = None
    python: str
    requirements: str | None = None
    workdir: str
    entry: list[str] = Field(min_length=1, max_length=30)
    mounts: list[MountIO] = Field(min_length=1, max_length=10)
    env: list[EnvIO] = Field(default=[], max_length=100)
    ports: list[PortIO] = Field(default=[], max_length=10)
    apt: list[str] = Field(default=[], max_length=50)


@router.post("/python/analyze")
async def analyze(request: Request, _: Operator, rt: RuntimeDep,
                  filename: str = Query("project.zip", max_length=200)) -> AnalysisOut:  # fmt: skip
    """Upload a project's .zip (request body): what Hivora found in it."""
    token, a = await PythonProjects(rt).analyze(request.stream(), filename)
    data: dict[str, Any] = asdict(a)
    return AnalysisOut(token=token, **data)


@router.post("/python", status_code=202)
async def deploy(body: ProjectIn, _: Operator, rt: RuntimeDep) -> DeployOut:
    spec = ProjectSpec(
        name=body.name, python=body.python, requirements=body.requirements,
        workdir=body.workdir, entry=body.entry,
        mounts=[Mount(m.source, m.target, m.data) for m in body.mounts],
        env=[e.model_dump() for e in body.env], ports=[p.model_dump() for p in body.ports],
        apt=body.apt,
    )  # fmt: skip
    app, job = await PythonProjects(rt).deploy(body.token, spec, body.zone)
    return DeployOut(app=app_out(rt, app, f"custom-{app.slug}"), job=job_ref(job))


@router.post("/{app_id}/python/code", status_code=202)
async def update_code(app_id: int, request: Request, _: Operator, rt: RuntimeDep) -> JobRef:
    """New code (request body: the project's .zip): code folders replaced, data kept."""
    return job_ref(await PythonProjects(rt).update_code(app_id, request.stream()))
