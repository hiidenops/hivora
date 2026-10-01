"""Static site routes, mounted under /api/v1/sites. Port, backups and removal are the
app routes' (a site is an app)."""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.apps.api import JobRef, job_ref
from hivora.state import AppStatus
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["sites"])


class SiteOut(BaseModel):
    id: int
    slug: str
    name: str
    port: int | None
    zone_id: int | None
    enabled: bool
    deployed: bool  # its first deploy has run: it can be enabled or disabled
    status: AppStatus


class SiteIn(BaseModel):
    name: str = Field(max_length=100)
    port: int = Field(ge=1, le=65535)
    zone: str | None = None


class SiteCreatedOut(BaseModel):
    site: SiteOut
    job: JobRef  # the deploy
    content_job: JobRef  # the first page, after the deploy


class SiteEnabledIn(BaseModel):
    enabled: bool


@router.get("")
async def list_sites(_: Viewer, rt: RuntimeDep) -> list[SiteOut]:
    return [SiteOut(**asdict(s)) for s in await rt.sites.list()]


@router.post("", status_code=202)
async def create_site(body: SiteIn, _: Operator, rt: RuntimeDep) -> SiteCreatedOut:
    site, deploy, content = await rt.sites.create(body.name, body.port, body.zone)
    return SiteCreatedOut(site=SiteOut(**asdict(site)), job=job_ref(deploy),
                          content_job=job_ref(content))  # fmt: skip


@router.put("/{app_id}/enabled", status_code=202)
async def set_enabled(app_id: int, body: SiteEnabledIn, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await rt.sites.set_enabled(app_id, body.enabled))
