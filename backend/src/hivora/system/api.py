"""HTTP routes of the system module."""

import platform

from fastapi import APIRouter
from pydantic import BaseModel

from hivora import __version__
from hivora.templates.catalog import host_arch
from hivora.web.deps import RuntimeDep, Viewer

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
