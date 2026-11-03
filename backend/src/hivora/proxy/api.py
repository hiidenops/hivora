"""HTTPS proxy routes, under /api/v1/proxy: the public domains and their certificates."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.web.deps import Operator, RuntimeDep

router = APIRouter(tags=["proxy"])


class RouteOut(BaseModel):
    id: int
    domain: str
    app_id: int
    app_name: str
    zone: str | None
    served: bool  # the app can still be reached (a zone, not behind a VPN, a web port)
    status: str  # valid, pending (Caddy is getting it), error
    error: str | None  # Caddy's last error getting the certificate
    expires_at: datetime | None
    issuer: str | None
    dns: list[str]  # the domain's addresses, as this machine resolves them
    points_here: bool  # one of them is this machine's public IP


class TargetOut(BaseModel):
    id: int
    name: str
    zone: str


class ProxyOut(BaseModel):
    installed: bool
    app_id: int | None
    running: bool
    public_ip: str | None
    routes: list[RouteOut]
    targets: list[TargetOut]  # apps a domain can go to


class RouteIn(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    app_id: int


class RouteCreatedOut(BaseModel):
    id: int
    job: int | None  # the proxy joins the app's zone first (a new revision)


@router.get("")
async def overview(_: Operator, rt: RuntimeDep) -> ProxyOut:
    return ProxyOut(**await rt.proxy.overview())


@router.post("/routes", status_code=201)
async def create(body: RouteIn, _: Operator, rt: RuntimeDep) -> RouteCreatedOut:
    rid, job = await rt.proxy.create(body.domain, body.app_id)
    return RouteCreatedOut(id=rid, job=job.id if job else None)


@router.delete("/routes/{rid}", status_code=204)
async def delete(rid: int, _: Operator, rt: RuntimeDep) -> None:
    await rt.proxy.delete(rid)
