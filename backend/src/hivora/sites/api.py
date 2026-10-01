"""Static site routes, mounted under /api/v1/sites. Port, backups and removal are the
app routes' (a site is an app)."""

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from hivora.apps.api import JobRef, job_ref
from hivora.sites.files import MAX_FILE
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


@router.put("/{app_id}/content", status_code=202)
async def replace_content(
    app_id: int, request: Request, _: Operator, rt: RuntimeDep,
    filename: str = Query("", max_length=200),
) -> JobRef:  # fmt: skip
    """Raw .zip body (streamed to disk, 200 MB max); the site's content is replaced by
    a job, all at once. A single top folder in the archive is removed."""
    return job_ref(await rt.sites.replace_content(app_id, filename, request.stream()))


class SiteFileOut(BaseModel):
    path: str
    size: int
    modified: datetime


class SiteFilesOut(BaseModel):
    files: list[SiteFileOut]  # .html, .css and .js only, sorted by path
    truncated: bool  # more files than listed


class SiteTextFileOut(BaseModel):
    path: str
    content: str
    sha256: str  # send it back as base_sha256 to save
    size: int


class SiteFileIn(BaseModel):
    path: str = Field(max_length=1024)
    content: str = Field(max_length=MAX_FILE)  # characters here; bytes checked after
    base_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")  # None: a new file


@router.get("/{app_id}/files")
async def list_files(app_id: int, _: Viewer, rt: RuntimeDep) -> SiteFilesOut:
    files, truncated = await rt.site_files.list(app_id)
    return SiteFilesOut(
        files=[SiteFileOut(path=f.path, size=f.size,
                           modified=datetime.fromtimestamp(f.modified, UTC)) for f in files],
        truncated=truncated,
    )  # fmt: skip


@router.get("/{app_id}/files/content")
async def read_file(
    app_id: int, _: Viewer, rt: RuntimeDep, path: str = Query(max_length=1024)
) -> SiteTextFileOut:
    return SiteTextFileOut(**asdict(await rt.site_files.read(app_id, path)))


@router.put("/{app_id}/files/content", status_code=202)
async def save_file(app_id: int, body: SiteFileIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """Saved by a job, all at once, if the file is still the one read (base_sha256)."""
    job = await rt.site_files.save(app_id, body.path, body.content, body.base_sha256)
    return job_ref(job)
