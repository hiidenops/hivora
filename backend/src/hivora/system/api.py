"""HTTP routes of the system module."""

import platform

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora import __version__
from hivora.system.secrets import SecretSetting
from hivora.templates.catalog import host_arch
from hivora.web.deps import Admin, RuntimeDep, Viewer

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    version: str


class SystemInfo(BaseModel):
    version: str
    docker_version: str | None
    arch: str
    python: str


@router.get("/health")
async def health() -> Health:
    """Public: used by the container healthcheck."""
    return Health(status="ok", version=__version__)


@router.get("/info")
async def info(_: Viewer, rt: RuntimeDep) -> SystemInfo:
    try:
        docker = await rt.gateway.ping()
    except Exception:
        docker = None
    return SystemInfo(
        version=__version__,
        docker_version=docker,
        arch=host_arch(),
        python=platform.python_version(),
    )


class IntegrationsOut(BaseModel):
    curseforge_api_key_set: bool  # the key itself is never sent back


class KeyIn(BaseModel):
    key: str = Field("", max_length=200)  # empty: remove the key


@router.get("/integrations")
async def integrations(_: Admin, rt: RuntimeDep) -> IntegrationsOut:
    return IntegrationsOut(
        curseforge_api_key_set=await rt.secrets.is_set(SecretSetting.CURSEFORGE_API_KEY)
    )


@router.put("/integrations/curseforge", status_code=204)
async def set_curseforge_key(body: KeyIn, _: Admin, rt: RuntimeDep) -> None:
    await rt.secrets.set(SecretSetting.CURSEFORGE_API_KEY, body.key.strip() or None)
