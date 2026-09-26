"""Game routes: modpack catalog (/api/v1/modpacks), game server tools (/api/v1/apps/{id}/game)."""

from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from hivora.games.engine import GameTools
from hivora.games.minecraft import MinecraftVersions
from hivora.games.modpacks import Loader, Source
from hivora.games.steam import SteamBranches
from hivora.jobs import Job
from hivora.system.secrets import SecretSetting
from hivora.templates.icons import MEDIA_TYPES
from hivora.templates.schema import Localized
from hivora.web.deps import Operator, RuntimeDep, Viewer

router = APIRouter(tags=["modpacks"])
game_router = APIRouter(tags=["game"])  # mounted under /apps
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
    page: int = Query(0, ge=0, le=400),
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


class ListEntryOut(BaseModel):
    name: str
    extra: str | None


class PlayerListOut(BaseModel):
    id: str
    label: Localized
    editable: bool
    enabled: bool | None  # None: always on
    name_pattern: str
    entries: list[ListEntryOut]


class ListsOut(BaseModel):
    running: bool
    lists: list[PlayerListOut]


class PlayerIn(BaseModel):
    name: str = Field(max_length=64)


class EnabledIn(BaseModel):
    enabled: bool


class CommandOut(BaseModel):
    output: str


class JobRefOut(BaseModel):
    id: int
    kind: str
    status: str


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


@game_router.get("/{app_id}/game/players")
async def players(app_id: int, _: Viewer, rt: RuntimeDep) -> PlayersOut:
    return PlayersOut(**asdict(await GameTools(rt).players(app_id)))


@game_router.get("/{app_id}/game/lists")
async def lists(app_id: int, _: Viewer, rt: RuntimeDep) -> ListsOut:
    running, found = await GameTools(rt).lists(app_id)
    return ListsOut(running=running, lists=[PlayerListOut(**asdict(x)) for x in found])


@game_router.post("/{app_id}/game/lists/{list_id}")
async def list_add(
    app_id: int, list_id: str, body: PlayerIn, _: Operator, rt: RuntimeDep
) -> CommandOut:
    return CommandOut(output=await GameTools(rt).change_list(app_id, list_id, body.name, add=True))


@game_router.delete("/{app_id}/game/lists/{list_id}/{name}")
async def list_remove(
    app_id: int, list_id: str, name: str, _: Operator, rt: RuntimeDep
) -> CommandOut:
    return CommandOut(output=await GameTools(rt).change_list(app_id, list_id, name, add=False))


@game_router.put("/{app_id}/game/lists/{list_id}/enabled", status_code=202)
async def list_enabled(
    app_id: int, list_id: str, body: EnabledIn, _: Operator, rt: RuntimeDep
) -> JobRefOut:
    """Intent change: new revision, the server restarts."""
    return _job(await GameTools(rt).set_list_enabled(app_id, list_id, body.enabled))


@game_router.get("/{app_id}/game/worlds")
async def worlds(app_id: int, _: Viewer, rt: RuntimeDep) -> WorldsOut:
    active, found = await GameTools(rt).worlds(app_id)
    return WorldsOut(active=active, worlds=[WorldOut(**asdict(x)) for x in found])


@game_router.post("/{app_id}/game/worlds", status_code=202)
async def world_import(
    app_id: int, request: Request, _: Operator, rt: RuntimeDep,
    name: str = Query(max_length=48), filename: str = Query("", max_length=200),
) -> JobRefOut:  # fmt: skip
    """Raw .zip body (streamed to disk, 10 GB max); extraction runs as a job."""
    return _job(await GameTools(rt).import_world(app_id, name, filename, request.stream()))


@game_router.put("/{app_id}/game/worlds/active", status_code=202)
async def world_activate(app_id: int, body: WorldIn, _: Operator, rt: RuntimeDep) -> JobRefOut:
    """Intent change: new revision, the server restarts on that world."""
    return _job(await GameTools(rt).activate_world(app_id, body.name))


@game_router.delete("/{app_id}/game/worlds/{name}", status_code=202)
async def world_delete(app_id: int, name: str, _: Operator, rt: RuntimeDep) -> JobRefOut:
    return _job(await GameTools(rt).delete_world(app_id, name))


@game_router.get("/{app_id}/game/worlds/{name}/download")
async def world_download(app_id: int, name: str, _: Operator, rt: RuntimeDep) -> StreamingResponse:
    stream = await GameTools(rt).download_world(app_id, name)
    return StreamingResponse(stream, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}.zip"',
        "Cache-Control": "no-store",
    })  # fmt: skip


class OptionOut(BaseModel):
    value: str
    label: str


_versions = MinecraftVersions()
_branches = SteamBranches()


@options_router.get("/minecraft_versions")
async def minecraft_versions(_: Viewer, snapshots: bool = False) -> list[OptionOut]:
    """Choices for fields declaring `options_from: minecraft_versions`."""
    return [OptionOut(**o) for o in await _versions.options(snapshots=snapshots)]


@options_router.get("/steam_branches")
async def steam_branches(_: Viewer, param: str = Query(pattern=r"^\d{1,10}$")) -> list[OptionOut]:
    """Choices for `options_from: steam_branches` (``options_param``: the server's app id)."""
    return [OptionOut(**o) for o in await _branches.options(param)]
