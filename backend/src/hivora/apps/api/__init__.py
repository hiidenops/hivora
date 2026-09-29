"""Application routes (/api/v1/apps)."""

from contextlib import suppress
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from hivora.apps.api import adoption, compose_edit, deploy, lifecycle, revisions
from hivora.apps.api.common import (
    AppOut,
    PortOut,
)
from hivora.apps.api.common import (  # re-exported: imported from here by pyapps and backups
    DeployOut as DeployOut,
)
from hivora.apps.api.common import (
    JobRef as JobRef,
)
from hivora.apps.api.common import (
    app_out as app_out,
)
from hivora.apps.api.common import (
    job_ref as job_ref,
)
from hivora.apps.models import Application, AppRevision, RevisionStatus
from hivora.core.errors import HivoraError, NotFoundError
from hivora.templates.models import TemplateVersion
from hivora.templates.schema import Localized
from hivora.web.deps import RuntimeDep, Viewer

router = APIRouter(tags=["apps"])


class ContainerOut(BaseModel):
    id: str
    name: str
    image: str
    state: str
    health: str


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
    python: bool = False  # a Python project sent as a .zip (new code can be sent)
    started_at: datetime | None  # main container, when running
    access: dict[str, str]  # where to connect (web / game)
    summary: list[SummaryItemOut]  # template-chosen settings (type, version...)


class RevisionOut(BaseModel):
    id: int
    number: int
    status: RevisionStatus
    inputs: dict[str, Any]
    created_at: datetime
    applied_at: datetime | None
    restorable: bool  # compiled from a known template version


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


def is_python(rt: RuntimeDep, template: str | None) -> bool:
    try:
        return bool(
            template and "python-project" in rt.catalog.get(template).template.metadata.tags
        )
    except NotFoundError:
        return False


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


@router.get("")
async def list_apps(_: Viewer, rt: RuntimeDep) -> list[AppOut]:
    async with rt.sessions() as session:
        rows = await session.execute(
            select(Application, TemplateVersion.slug)
            .outerjoin(TemplateVersion, Application.template_version_id == TemplateVersion.id)
            .order_by(Application.name)
        )
        return [app_out(rt, app, template) for app, template in rows]


router.include_router(deploy.plan_router)


router.include_router(adoption.router)


router.include_router(deploy.router)
router.post("", status_code=202)(deploy.deploy)  # empty path: cannot sit in an included router


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
            python=is_python(rt, template),
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


router.include_router(lifecycle.router)


router.include_router(revisions.zone_router)


router.include_router(lifecycle.removal_router)


router.include_router(revisions.router)


router.include_router(compose_edit.router)
