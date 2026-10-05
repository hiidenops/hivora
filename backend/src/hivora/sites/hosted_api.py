"""Routes of the sites an nginx app hosts, mounted under /api/v1/apps: the sites are the
app's (app -> sites), each on its own port. A change that moves a port first has a plan
(``recreate``: the container is recreated, every site stops about a second)."""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.apps.api import JobRef, job_ref
from hivora.jobs import Job
from hivora.sites.hosting import HostedSite, SiteHost, SitePlan
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["sites"])


class HostedSiteOut(BaseModel):
    id: int
    slug: str
    name: str
    main: bool  # the html volume, on the app's web port
    port: int | None
    server_name: str | None
    enabled: bool
    url: str | None


class SiteHostOut(BaseModel):
    app_id: int
    slug: str
    name: str
    upgrade_required: bool  # nginx on template 1.0.0: update the app to add sites
    stopped: bool  # port changes refused until the app is started
    max_sites: int
    sites: list[HostedSiteOut]


class HostedSiteIn(BaseModel):
    name: str = Field(max_length=100)
    port: int = Field(ge=1, le=65535)
    slug: str | None = Field(default=None, max_length=63)  # default: from the name
    server_name: str | None = Field(default=None, max_length=253)  # default: any name


class SitePortIn(BaseModel):
    port: int = Field(ge=1, le=65535)


class SiteServerNameIn(BaseModel):
    server_name: str | None = Field(max_length=253)  # None: any name


class SiteToggleIn(BaseModel):
    enabled: bool


class SitePlanOut(BaseModel):
    recreate: bool  # the container is recreated: every site of this nginx stops ~1 s
    revision: int | None  # the revision this change makes (None: none)
    diff: str
    ports_before: list[int]
    ports_after: list[int]


class SiteChangeOut(BaseModel):
    site: HostedSiteOut | None  # None once removed
    job: JobRef | None  # the revision's job (recreates the container)
    config_job: JobRef  # nginx's files


def _host(host: SiteHost) -> SiteHostOut:
    return SiteHostOut(
        **{**asdict(host), "sites": [HostedSiteOut(**asdict(s)) for s in host.sites]}
    )


def _plan(plan: SitePlan) -> SitePlanOut:
    return SitePlanOut(**asdict(plan))


async def _site(rt: RuntimeDep, app_id: int, site_id: int) -> HostedSiteOut:
    site: HostedSite = next(
        s for s in (await rt.site_hosting.view(app_id)).sites if s.id == site_id
    )
    return HostedSiteOut(**asdict(site))


def _change(site: HostedSiteOut | None, job: Job | None, config: Job) -> SiteChangeOut:
    return SiteChangeOut(site=site, job=job_ref(job) if job else None, config_job=job_ref(config))


@router.get("/{app_id}/sites")
async def list_hosted_sites(app_id: int, _: Viewer, rt: RuntimeDep) -> SiteHostOut:
    return _host(await rt.site_hosting.view(app_id))


@router.post("/{app_id}/sites/hosting")
async def enable_site_hosting(app_id: int, _: Operator, rt: RuntimeDep) -> SiteHostOut:
    """An nginx from the catalog starts hosting sites (no change if it already does)."""
    return _host(await rt.site_hosting.enable_hosting(app_id))


@router.post("/{app_id}/sites/plan")
async def plan_hosted_site(
    app_id: int, body: HostedSiteIn, _: Operator, rt: RuntimeDep
) -> SitePlanOut:
    return _plan(await rt.site_hosting.plan_add(app_id, body.name, body.port, body.slug,
                                                body.server_name))  # fmt: skip


@router.post("/{app_id}/sites", status_code=202)
async def add_hosted_site(
    app_id: int, body: HostedSiteIn, _: Operator, rt: RuntimeDep
) -> SiteChangeOut:
    site_id, update, config = await rt.site_hosting.add(app_id, body.name, body.port, body.slug,
                                                        body.server_name)  # fmt: skip
    return _change(await _site(rt, app_id, site_id), update, config)


@router.put("/{app_id}/sites/{site_id}/enabled", status_code=202)
async def set_hosted_site_enabled(
    app_id: int, site_id: int, body: SiteToggleIn, _: Operator, rt: RuntimeDep
) -> JobRef:
    """nginx's files only: the site's port stays published, nothing is recreated."""
    return job_ref(await rt.site_hosting.set_enabled(app_id, site_id, body.enabled))


@router.put("/{app_id}/sites/{site_id}/server-name", status_code=202)
async def set_hosted_site_server_name(
    app_id: int, site_id: int, body: SiteServerNameIn, _: Operator, rt: RuntimeDep
) -> JobRef:
    return job_ref(await rt.site_hosting.set_server_name(app_id, site_id, body.server_name))


@router.post("/{app_id}/sites/{site_id}/port/plan")
async def plan_hosted_site_port(
    app_id: int, site_id: int, body: SitePortIn, _: Operator, rt: RuntimeDep
) -> SitePlanOut:
    return _plan(await rt.site_hosting.plan_port(app_id, site_id, body.port))


@router.put("/{app_id}/sites/{site_id}/port", status_code=202)
async def change_hosted_site_port(
    app_id: int, site_id: int, body: SitePortIn, _: Operator, rt: RuntimeDep
) -> SiteChangeOut:
    update, config = await rt.site_hosting.change_port(app_id, site_id, body.port)
    return _change(await _site(rt, app_id, site_id), update, config)


@router.get("/{app_id}/sites/{site_id}/removal-plan")
async def plan_hosted_site_removal(
    app_id: int, site_id: int, _: Operator, rt: RuntimeDep
) -> SitePlanOut:
    return _plan(await rt.site_hosting.plan_remove(app_id, site_id))


@router.delete("/{app_id}/sites/{site_id}", status_code=202)
async def remove_hosted_site(
    app_id: int, site_id: int, _: Operator, rt: RuntimeDep, remove_data: bool = False
) -> SiteChangeOut:
    """nginx stops serving it, then its port goes; its files stay unless remove_data."""
    config, update = await rt.site_hosting.remove(app_id, site_id, remove_data=remove_data)
    return _change(None, update, config)
