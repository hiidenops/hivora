"""Response models and conversions shared by the app routes (and by `pyapps`, `backups`)."""

from datetime import datetime

from pydantic import BaseModel

from hivora.apps.models import Application, DesiredState
from hivora.apps.service import DeployPlan
from hivora.jobs import Job
from hivora.state import AppStatus
from hivora.web.deps import RuntimeDep

_RUNNING = {AppStatus.HEALTHY, AppStatus.STARTING, AppStatus.DEGRADED}


class PortOut(BaseModel):
    service: str
    container_port: int
    host_port: int | None
    protocol: str
    purpose: str
    exposure: str
    host_ip: str | None


class ConflictOut(BaseModel):
    port: int
    protocol: str
    used_by: str
    suggestion: int | None


class PlanOut(BaseModel):
    slug: str
    name: str
    zone: str | None
    compose_yaml: str
    ports: list[PortOut]
    volumes: list[str]
    conflicts: list[ConflictOut]
    access: dict[str, str]
    public_ports: list[int]  # exposed on every interface: bypasses UFW (docs §9)


class JobRef(BaseModel):
    id: int
    kind: str
    status: str


class AppOut(BaseModel):
    id: int
    slug: str
    name: str
    template: str | None
    icon_url: str | None
    zone_id: int | None
    origin: str
    desired_state: DesiredState
    status: AppStatus
    drift: bool  # intent and reality disagree
    created_at: datetime


class DeployOut(BaseModel):
    app: AppOut
    job: JobRef


def job_ref(job: Job) -> JobRef:
    return JobRef(id=job.id, kind=job.kind.value, status=job.status.value)


def has_drift(desired: DesiredState, status: AppStatus) -> bool:
    if desired is DesiredState.RUNNING:
        return status not in _RUNNING
    return status in _RUNNING


def app_out(rt: RuntimeDep, app: Application, template: str | None) -> AppOut:
    status = rt.state.store.app(app.slug).status
    icon = f"/api/v1/templates/{template}/icon" if template and rt.icons.path(template) else None
    return AppOut(
        id=app.id,
        slug=app.slug,
        name=app.name,
        template=template,
        icon_url=icon,
        zone_id=app.zone_id,
        origin=app.origin.value,
        desired_state=app.desired_state,
        status=status,
        drift=has_drift(app.desired_state, status),
        created_at=app.created_at,
    )


def plan_out(plan: DeployPlan) -> PlanOut:
    ports = [PortOut(service=p.service, container_port=p.container_port, host_port=p.host_port,
                     protocol=p.protocol, purpose=p.purpose, exposure=p.exposure,
                     host_ip=p.host_ip)
             for s in plan.compiled.services for p in s.ports]  # fmt: skip
    return PlanOut(
        slug=plan.slug, name=plan.name, zone=plan.zone.slug if plan.zone else None,
        compose_yaml=plan.compiled.compose_yaml, ports=ports,
        volumes=[str(v.source) for s in plan.compiled.services for v in s.volumes],
        conflicts=[ConflictOut(port=c.port, protocol=c.protocol, used_by=c.used_by,
                               suggestion=c.suggestion) for c in plan.conflicts],
        access=plan.compiled.access,
        public_ports=[p.host_port for p in ports if p.exposure == "public" and p.host_port],
    )  # fmt: skip
