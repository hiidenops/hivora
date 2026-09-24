"""Modpack catalog routes (/api/v1/modpacks)."""

from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from hivora.games.minecraft import MinecraftTools, MinecraftVersions
from hivora.games.modpacks import Loader, Source
from hivora.jobs import Job
from hivora.system.secrets import SecretSetting
from hivora.templates.icons import MEDIA_TYPES
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["modpacks"])
minecraft_router = APIRouter(tags=["minecraft"])  # mounted under /apps
options_router = APIRouter(tags=["options"])  # dynamic choices for template fields


class ModpackOut(BaseModel):
    source: Source
    slug: str
    title: str
    summary: str
    icon_url: str | None  # relayed by Hivora
    downloads: int
    mc_versions: list[str]
    loaders: list[str]
    url: str


@router.get("/search")
async def search(
    _: Viewer, rt: RuntimeDep, source: Source = "modrinth",
    q: str = Query("", max_length=100), loader: Loader | None = None,
    mc_version: str | None = Query(None, pattern=r"^\d+\.\d+(\.\d+)?$"),
    page: int = Query(0, ge=0, le=50),
) -> list[ModpackOut]:  # fmt: skip
    key = await rt.secrets.get(SecretSetting.CURSEFORGE_API_KEY) if source == "curseforge" else None
    packs = await rt.modpacks.search(source, q.strip(), loader=loader, mc_version=mc_version,
                                     page=page, curseforge_key=key)  # fmt: skip
    return [
        ModpackOut(**{k: v for k, v in asdict(p).items() if k != "icon"},
                   icon_url=f"/api/v1/modpacks/icon?url={p.icon}" if p.icon else None)
        for p in packs
    ]  # fmt: skip


@router.get("/icon")
async def icon(url: str, _: Viewer, rt: RuntimeDep) -> FileResponse:
    path, ext = await rt.modpacks.icon(url)
    return FileResponse(path, media_type=MEDIA_TYPES[ext], headers={
        "Cache-Control": "private, max-age=604800", "X-Content-Type-Options": "nosniff",
    })  # fmt: skip


class PlayersOut(BaseModel):
    running: bool
    online: int | None
    max: int | None
    names: list[str]


class OperatorOut(BaseModel):
    name: str
    level: int


class AccessOut(BaseModel):
    running: bool
    whitelist_enabled: bool
    whitelist: list[str]
    ops: list[OperatorOut]


class PlayerIn(BaseModel):
    name: str = Field(max_length=16)


class EnabledIn(BaseModel):
    enabled: bool


class CommandOut(BaseModel):
    output: str


class JobRefOut(BaseModel):
    id: int
    kind: str
    status: str


@minecraft_router.get("/{app_id}/minecraft/players")
async def players(app_id: int, _: Viewer, rt: RuntimeDep) -> PlayersOut:
    return PlayersOut(**asdict(await MinecraftTools(rt).players(app_id)))


@minecraft_router.get("/{app_id}/minecraft/access")
async def access(app_id: int, _: Viewer, rt: RuntimeDep) -> AccessOut:
    return AccessOut(**await MinecraftTools(rt).access(app_id))


@minecraft_router.post("/{app_id}/minecraft/whitelist")
async def whitelist_add(app_id: int, body: PlayerIn, _: Operator, rt: RuntimeDep) -> CommandOut:
    return CommandOut(output=await MinecraftTools(rt).whitelist(app_id, body.name, add=True))


@minecraft_router.delete("/{app_id}/minecraft/whitelist/{name}")
async def whitelist_remove(app_id: int, name: str, _: Operator, rt: RuntimeDep) -> CommandOut:
    return CommandOut(output=await MinecraftTools(rt).whitelist(app_id, name, add=False))


@minecraft_router.post("/{app_id}/minecraft/ops")
async def op_add(app_id: int, body: PlayerIn, _: Operator, rt: RuntimeDep) -> CommandOut:
    return CommandOut(output=await MinecraftTools(rt).operator(app_id, body.name, add=True))


@minecraft_router.delete("/{app_id}/minecraft/ops/{name}")
async def op_remove(app_id: int, name: str, _: Operator, rt: RuntimeDep) -> CommandOut:
    return CommandOut(output=await MinecraftTools(rt).operator(app_id, name, add=False))


@minecraft_router.put("/{app_id}/minecraft/whitelist-enabled", status_code=202)
async def whitelist_enabled(app_id: int, body: EnabledIn, _: Operator, rt: RuntimeDep) -> JobRefOut:
    """Intent change: new revision, the server restarts."""
    return _job(await MinecraftTools(rt).set_whitelist_enabled(app_id, body.enabled))


class WorldOut(BaseModel):
    name: str
    size: int
    modified: float
    active: bool


class WorldsOut(BaseModel):
    active: str
    worlds: list[WorldOut]


class WorldIn(BaseModel):
    name: str = Field(max_length=48)


def _job(job: Job) -> JobRefOut:
    return JobRefOut(id=job.id, kind=job.kind.value, status=job.status.value)


@minecraft_router.get("/{app_id}/minecraft/worlds")
async def worlds(app_id: int, _: Viewer, rt: RuntimeDep) -> WorldsOut:
    active, found = await MinecraftTools(rt).worlds(app_id)
    return WorldsOut(active=active, worlds=[WorldOut(**asdict(x)) for x in found])


@minecraft_router.post("/{app_id}/minecraft/worlds", status_code=202)
async def world_import(
    app_id: int, request: Request, _: Operator, rt: RuntimeDep,
    name: str = Query(max_length=48), filename: str = Query("", max_length=200),
) -> JobRefOut:  # fmt: skip
    """Raw .zip body (streamed to disk, 10 GB max); extraction runs as a job."""
    return _job(await MinecraftTools(rt).import_world(app_id, name, filename, request.stream()))


@minecraft_router.put("/{app_id}/minecraft/worlds/active", status_code=202)
async def world_activate(app_id: int, body: WorldIn, _: Operator, rt: RuntimeDep) -> JobRefOut:
    """Intent change: new revision, the server restarts on that world."""
    return _job(await MinecraftTools(rt).activate_world(app_id, body.name))


@minecraft_router.delete("/{app_id}/minecraft/worlds/{name}", status_code=202)
async def world_delete(app_id: int, name: str, _: Operator, rt: RuntimeDep) -> JobRefOut:
    return _job(await MinecraftTools(rt).delete_world(app_id, name))


@minecraft_router.get("/{app_id}/minecraft/worlds/{name}/download")
async def world_download(app_id: int, name: str, _: Operator, rt: RuntimeDep) -> StreamingResponse:
    stream = await MinecraftTools(rt).download_world(app_id, name)
    return StreamingResponse(stream, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}.zip"',
        "Cache-Control": "no-store",
    })  # fmt: skip


class OptionOut(BaseModel):
    value: str
    label: str


_versions = MinecraftVersions()


@options_router.get("/minecraft_versions")
async def minecraft_versions(_: Viewer, snapshots: bool = False) -> list[OptionOut]:
    """Choices for fields declaring `options_from: minecraft_versions`."""
    return [OptionOut(**o) for o in await _versions.options(snapshots=snapshots)]
