"""Modpack catalog routes (/api/v1/modpacks)."""

from dataclasses import asdict

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from hivora.games.modpacks import Loader, Source
from hivora.system.secrets import SecretSetting
from hivora.templates.icons import MEDIA_TYPES
from hivora.web.deps import RuntimeDep, Viewer

router = APIRouter(tags=["modpacks"])


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
