"""Deployment routes: from a catalog template, or from any registry image (free image).

Two routers: in the public route order, `POST /plan` comes before the adoption routes
and the other deployment routes after them, and that order is kept. `deploy` (path "")
is registered by the parent router: FastAPI refuses an empty path in an included router.
"""

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from hivora.apps.api.common import DeployOut, PlanOut, app_out, job_ref, plan_out
from hivora.apps.service import DeployRequest
from hivora.templates.catalog import host_arch
from hivora.templates.custom import CustomEnv, CustomPort
from hivora.web.deps import Operator, RuntimeDep

plan_router = APIRouter()
router = APIRouter()


class DeployIn(BaseModel):
    template: str
    name: str = Field(max_length=100)
    inputs: dict[str, Any] = {}
    slug: str | None = Field(default=None, max_length=50)
    zone: str | None = None


def to_request(body: DeployIn) -> DeployRequest:
    return DeployRequest(
        template=body.template, name=body.name, inputs=body.inputs, slug=body.slug, zone=body.zone
    )


@plan_router.post("/plan")
async def plan(body: DeployIn, _: Operator, rt: RuntimeDep) -> PlanOut:
    """Preview: generated compose, ports, conflicts. Nothing is written."""
    async with rt.sessions() as session:
        return plan_out(await rt.apps.plan_deploy(session, to_request(body)))


class CustomPortIn(BaseModel):
    container: int = Field(ge=1, le=65535)
    host: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    exposure: Literal["lan", "public", "internal"] = "lan"
    web: bool = False


class CustomEnvIn(BaseModel):
    key: str = Field(max_length=128)
    value: str = Field(default="", max_length=4096)
    secret: bool = False


class CustomIn(BaseModel):
    """Any registry image: Docker Hub (nginx, grafana/grafana:12), ghcr.io/…"""

    name: str = Field(max_length=100)
    image: str = Field(max_length=300)
    zone: str | None = None
    ports: list[CustomPortIn] = Field(default=[], max_length=20)
    volumes: list[str] = Field(default=[], max_length=20)
    env: list[CustomEnvIn] = Field(default=[], max_length=100)


class ImageOut(BaseModel):
    name: str
    tag: str
    digest: str
    platforms: list[str]
    compatible: bool  # has a build for this machine
    ports: list[CustomPortIn]
    volumes: list[str]
    env: list[CustomEnvIn]


@router.get("/images/inspect")
async def inspect_image(_: Operator, rt: RuntimeDep, ref: str = Query(max_length=300)) -> ImageOut:
    """What the registry says about an image: pre-fills the free image form."""
    arch = host_arch()
    info = await rt.apps.registry.inspect(ref, arch)
    return ImageOut(
        name=info.ref.name, tag=info.ref.tag, digest=info.digest, platforms=info.platforms,
        compatible=arch in info.platforms,
        ports=[CustomPortIn(container=p, host=p, protocol="udp" if proto == "udp" else "tcp")
               for p, proto in info.ports if proto in ("tcp", "udp")],
        volumes=info.volumes,
        env=[CustomEnvIn(key=k, value=v) for k, v in info.env.items()],
    )  # fmt: skip


async def _custom(rt: RuntimeDep, body: CustomIn) -> DeployRequest:
    return await rt.apps.custom_request(
        body.name, body.image, body.zone,
        [CustomPort(p.container, p.host, p.protocol, p.exposure, p.web) for p in body.ports],
        body.volumes, [CustomEnv(e.key, e.value, e.secret) for e in body.env],
    )  # fmt: skip


@router.post("/custom/plan")
async def plan_custom(body: CustomIn, _: Operator, rt: RuntimeDep) -> PlanOut:
    """Preview the compose generated for a free image. Nothing is written."""
    req = await _custom(rt, body)
    async with rt.sessions() as session:
        return plan_out(await rt.apps.plan_deploy(session, req))


@router.post("/custom", status_code=202)
async def deploy_custom(body: CustomIn, _: Operator, rt: RuntimeDep) -> DeployOut:
    req = await _custom(rt, body)
    app, job = await rt.apps.deploy(req)
    return DeployOut(app=app_out(rt, app, req.template), job=job_ref(job))


async def deploy(body: DeployIn, _: Operator, rt: RuntimeDep) -> DeployOut:
    app, job = await rt.apps.deploy(to_request(body))
    return DeployOut(app=app_out(rt, app, body.template), job=job_ref(job))
