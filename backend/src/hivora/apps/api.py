"""Application routes (/api/v1/apps)."""

from contextlib import suppress
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from hivora.apps.models import Application, AppRevision, DesiredState, RevisionStatus
from hivora.apps.service import DeployPlan, DeployRequest, UpdatePlan
from hivora.core.errors import HivoraError, NotFoundError
from hivora.jobs import Job
from hivora.state import AppStatus
from hivora.templates.catalog import host_arch
from hivora.templates.custom import CustomEnv, CustomPort
from hivora.templates.models import TemplateVersion
from hivora.templates.schema import Localized
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["apps"])

_RUNNING = {AppStatus.HEALTHY, AppStatus.STARTING, AppStatus.DEGRADED}


class DeployIn(BaseModel):
    template: str
    name: str = Field(max_length=100)
    inputs: dict[str, Any] = {}
    slug: str | None = Field(default=None, max_length=50)
    zone: str | None = None


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


class ContainerOut(BaseModel):
    id: str
    name: str
    image: str
    state: str
    health: str


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


class ConsoleCommandOut(BaseModel):
    command: str
    description: Localized


class ConsoleInfoOut(BaseModel):
    server: bool  # the template declares a server console (e.g. rcon-cli)
    commands: list[ConsoleCommandOut]


class SummaryItemOut(BaseModel):
    label: Localized
    value: Localized


class GameCapsOut(BaseModel):
    players: bool
    lists: bool
    worlds: bool
    world_import: bool
    world_activate: bool


class AppDetailOut(AppOut):
    revision: int | None
    containers: list[ContainerOut]
    ports: list[PortOut]
    volumes: list[str]
    console: ConsoleInfoOut
    game: GameCapsOut | None  # game tools the template declares
    vpn: bool  # a VPN Hivora manages (clients, zones reached)
    started_at: datetime | None  # main container, when running
    access: dict[str, str]  # where to connect (web / game)
    summary: list[SummaryItemOut]  # template-chosen settings (type, version...)


class DeployOut(BaseModel):
    app: AppOut
    job: JobRef


class RevisionOut(BaseModel):
    id: int
    number: int
    status: RevisionStatus
    inputs: dict[str, Any]
    created_at: datetime
    applied_at: datetime | None
    restorable: bool  # compiled from a known template version


class UpgradeOut(BaseModel):
    kind: Literal["template", "image"]
    current: str  # template version, or tag@digest for a free image
    latest: str
    available: bool


class ApplyIn(BaseModel):
    reset_data: bool = False  # confirms erasing the data when the change requires it


class SettingsOut(BaseModel):
    template: str
    version: str
    form: dict[str, Any]
    values: dict[str, Any]
    secrets_set: list[str]


class SettingsIn(BaseModel):
    inputs: dict[str, Any] = {}
    reset_data: bool = False  # confirms a change that erases the app data


class ResetOut(BaseModel):
    fields: list[str]
    labels: list[Localized]  # of those fields, in the applied template
    volumes: list[str]
    size: int


class UpdatePlanOut(PlanOut):
    revision: int
    diff: str
    reset: ResetOut | None  # set when applying erases the app data


class RemovalPlanOut(BaseModel):
    slug: str
    containers: list[str]
    files: list[str]
    data: list[str]


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


def console_info(rt: RuntimeDep, template: str | None) -> ConsoleInfoOut:
    game = None
    if template:
        try:
            game = rt.catalog.get(template).template.game
        except NotFoundError:  # template removed from the catalog since deployment
            game = None
    return ConsoleInfoOut(
        server=bool(game and game.console),
        commands=[ConsoleCommandOut(command=c.command, description=c.description)
                  for c in (game.commands if game else [])],
    )  # fmt: skip


async def app_summary(
    rt: RuntimeDep, session: Any, app_id: int, template: str | None
) -> list[SummaryItemOut]:
    """The template's `summary` fields with their current values (option labels)."""
    try:
        t = rt.catalog.get(template).template if template else None
    except NotFoundError:
        return []
    if t is None or not t.summary:
        return []
    values = (await rt.apps.current_settings(session, app_id)).values
    fields = {f.id: f for f in t.form.fields}
    items = []
    for fid in t.summary:
        f, value = fields[fid], values.get(fid)
        if value in (None, ""):
            continue
        option = next((o for o in f.options or [] if o.value == value), None)
        items.append(SummaryItemOut(label=f.label, value=option.label if option else str(value)))
    return items


def has_vpn(rt: RuntimeDep, template: str | None) -> bool:
    try:
        return bool(template and rt.catalog.get(template).template.vpn)
    except NotFoundError:
        return False


def game_caps(rt: RuntimeDep, template: str | None) -> GameCapsOut | None:
    from hivora.games.engine import GameTools

    try:
        game = rt.catalog.get(template).template.game if template else None
    except NotFoundError:
        return None
    caps = GameTools.capabilities(game)
    return GameCapsOut(**caps) if caps else None


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


def to_request(body: DeployIn) -> DeployRequest:
    return DeployRequest(
        template=body.template, name=body.name, inputs=body.inputs, slug=body.slug, zone=body.zone
    )


@router.get("")
async def list_apps(_: Viewer, rt: RuntimeDep) -> list[AppOut]:
    async with rt.sessions() as session:
        rows = await session.execute(
            select(Application, TemplateVersion.slug)
            .outerjoin(TemplateVersion, Application.template_version_id == TemplateVersion.id)
            .order_by(Application.name)
        )
        return [app_out(rt, app, template) for app, template in rows]


@router.post("/plan")
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


@router.post("", status_code=202)
async def deploy(body: DeployIn, _: Operator, rt: RuntimeDep) -> DeployOut:
    app, job = await rt.apps.deploy(to_request(body))
    return DeployOut(app=app_out(rt, app, body.template), job=job_ref(job))


@router.get("/{app_id}")
async def get_app(app_id: int, _: Viewer, rt: RuntimeDep) -> AppDetailOut:
    async with rt.sessions() as session:
        app = await rt.apps.get(session, app_id)
        template = await session.scalar(
            select(TemplateVersion.slug).where(TemplateVersion.id == app.template_version_id)
        )
        revision = (await session.get(AppRevision, app.current_revision_id)
                    if app.current_revision_id else None)  # fmt: skip
        state = rt.state.store.app(app.slug)
        *_unused, main = await rt.apps.main_container(session, app.id)
        access = await rt.apps.access_of(session, app)
        summary = await app_summary(rt, session, app.id, template)
        started_at = main.started_at if main else None
        if main and started_at is None:  # listings omit it: ask Docker once
            with suppress(HivoraError):
                started_at = (await rt.gateway.get_container(main.id)).started_at
        return AppDetailOut(
            **app_out(rt, app, template).model_dump(),
            revision=revision.number if revision else None,
            containers=[ContainerOut(id=c.id[:12], name=c.name, image=c.image,
                                     state=c.state.value, health=c.health.value)
                        for c in state.containers],
            ports=[PortOut(service=s.name, container_port=p.container_port,
                           host_port=p.host_port, protocol=p.protocol, purpose=p.purpose,
                           exposure=p.exposure.value, host_ip=p.host_ip)
                   for s in app.services for p in s.ports],
            volumes=[v.source for s in app.services for v in s.volumes],
            console=console_info(rt, template),
            game=game_caps(rt, template),
            vpn=has_vpn(rt, template),
            started_at=started_at,
            access=access,
            summary=summary,
        )  # fmt: skip


@router.get("/{app_id}/compose")
async def get_compose(app_id: int, _: Viewer, rt: RuntimeDep) -> dict[str, str]:
    async with rt.sessions() as session:
        app = await rt.apps.get(session, app_id)
        revision_id = app.current_revision_id or await session.scalar(
            select(AppRevision.id).where(AppRevision.app_id == app.id)
            .order_by(AppRevision.number.desc())
        )  # fmt: skip
        if revision_id is None:
            raise NotFoundError("no revision")
        revision = await session.get_one(AppRevision, revision_id)
        return {"compose_yaml": revision.compose_yaml}


@router.get("/{app_id}/revisions")
async def list_revisions(app_id: int, _: Viewer, rt: RuntimeDep) -> list[RevisionOut]:
    async with rt.sessions() as session:
        await rt.apps.get(session, app_id)
        rows = await session.scalars(
            select(AppRevision).where(AppRevision.app_id == app_id)
            .order_by(AppRevision.number.desc())
        )  # fmt: skip
        return [
            RevisionOut(
                id=r.id,
                number=r.number,
                status=r.status,
                inputs=r.inputs,
                created_at=r.created_at,
                applied_at=r.applied_at,
                restorable=r.template_version_id is not None,
            )
            for r in rows
        ]


@router.post("/{app_id}/start", status_code=202)
async def start(app_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await rt.apps.start(app_id))


@router.post("/{app_id}/stop", status_code=202)
async def stop(app_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await rt.apps.stop(app_id))


@router.post("/{app_id}/restart", status_code=202)
async def restart(app_id: int, _: Operator, rt: RuntimeDep) -> JobRef:
    return job_ref(await rt.apps.restart(app_id))


class ZoneIn(BaseModel):
    zone: str | None  # zone slug; None: no zone


@router.put("/{app_id}/zone", status_code=202)
async def move_zone(app_id: int, body: ZoneIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """New revision in the target zone (joins its network if it shares one)."""
    return job_ref(await rt.apps.move_zone(app_id, body.zone))


@router.get("/{app_id}/removal-plan")
async def removal_plan(app_id: int, _: Operator, rt: RuntimeDep) -> RemovalPlanOut:
    p = await rt.apps.removal_plan(app_id)
    return RemovalPlanOut(slug=p.slug, containers=p.containers, files=p.files, data=p.data)


@router.delete("/{app_id}", status_code=202)
async def remove(app_id: int, _: Operator, rt: RuntimeDep, remove_data: bool = False) -> JobRef:
    """Data is kept unless ``remove_data=true`` is passed explicitly."""
    return job_ref(await rt.apps.remove(app_id, remove_data=remove_data))


@router.get("/{app_id}/settings")
async def get_settings(app_id: int, _: Operator, rt: RuntimeDep) -> SettingsOut:
    async with rt.sessions() as session:
        st = await rt.apps.current_settings(session, app_id)
    t = st.entry.template
    return SettingsOut(template=st.entry.slug, version=t.metadata.version,
                       form=t.form.model_dump(by_alias=True, exclude_none=True),
                       values=st.values, secrets_set=st.secrets_set)  # fmt: skip


def update_plan_out(upd: UpdatePlan) -> UpdatePlanOut:
    fields = {f.id: f.label for f in upd.plan.entry.template.form.fields}
    reset = (
        ResetOut(fields=upd.reset_fields, labels=[fields[f] for f in upd.reset_fields],
                 volumes=sorted(upd.reset_volumes), size=upd.reset_size)
        if upd.reset_fields else None
    )  # fmt: skip
    return UpdatePlanOut(**plan_out(upd.plan).model_dump(), revision=upd.number, diff=upd.diff,
                         reset=reset)  # fmt: skip


@router.post("/{app_id}/settings/plan")
async def plan_settings(
    app_id: int, body: SettingsIn, _: Operator, rt: RuntimeDep
) -> UpdatePlanOut:
    """Preview: new compose and its diff against the current revision. Nothing is written."""
    async with rt.sessions() as session:
        return update_plan_out(await rt.apps.plan_update(session, app_id, body.inputs))


@router.put("/{app_id}/settings", status_code=202)
async def update_settings(app_id: int, body: SettingsIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """New revision from these inputs, applied by a job (secrets left empty are kept)."""
    return job_ref(await rt.apps.update(app_id, body.inputs, reset_data=body.reset_data))


@router.get("/{app_id}/upgrade")
async def upgrade_status(app_id: int, _: Viewer, rt: RuntimeDep) -> UpgradeOut:
    """Newer template version, or newer image for a free image (asks its registry)."""
    async with rt.sessions() as session:
        st = await rt.apps.upgrade_status(session, app_id)
    return UpgradeOut(kind=st.kind, current=st.current, latest=st.latest, available=st.available)


@router.post("/{app_id}/upgrade/plan")
async def plan_upgrade(app_id: int, _: Operator, rt: RuntimeDep) -> UpdatePlanOut:
    async with rt.sessions() as session:
        return update_plan_out(await rt.apps.plan_upgrade(session, app_id))


@router.post("/{app_id}/upgrade", status_code=202)
async def upgrade(app_id: int, body: ApplyIn, _: Operator, rt: RuntimeDep) -> JobRef:
    """Same settings, newest template (or image): a new revision."""
    return job_ref(await rt.apps.upgrade(app_id, reset_data=body.reset_data))


@router.post("/{app_id}/revisions/{number}/plan")
async def plan_restore(app_id: int, number: int, _: Operator, rt: RuntimeDep) -> UpdatePlanOut:
    async with rt.sessions() as session:
        return update_plan_out(await rt.apps.plan_restore(session, app_id, number))


@router.post("/{app_id}/revisions/{number}/restore", status_code=202)
async def restore(app_id: int, number: int, body: ApplyIn, _: Operator,
                  rt: RuntimeDep) -> JobRef:  # fmt: skip
    """A new revision with that revision's settings and template version."""
    return job_ref(await rt.apps.restore(app_id, number, reset_data=body.reset_data))
