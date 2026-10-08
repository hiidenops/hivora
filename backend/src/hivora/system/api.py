"""HTTP routes of the system module."""

import platform

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora import __version__
from hivora.system.secrets import SecretSetting
from hivora.web.deps import Admin, RuntimeDep, Viewer

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    version: str
    first_start: bool  # admin/admin still unchanged: the login page shows the hint


class SystemInfo(BaseModel):
    version: str
    docker_version: str | None
    arch: str
    python: str


@router.get("/health")
async def health(rt: RuntimeDep) -> Health:
    """Public: used by the container healthcheck and the login page."""
    return Health(status="ok", version=__version__, first_start=await rt.auth.first_start())


@router.get("/info")
async def info(_: Viewer, rt: RuntimeDep) -> SystemInfo:
    try:
        docker = await rt.gateway.ping()
    except Exception:
        docker = None
    return SystemInfo(
        version=__version__,
        docker_version=docker,
        arch=rt.catalog.host_arch(),
        python=platform.python_version(),
    )


class IntegrationsOut(BaseModel):
    curseforge_api_key_set: bool  # the key itself is never sent back
    public_address: str | None  # set by an admin (IP or domain)
    detected_public_ip: str | None  # auto-detected


class KeyIn(BaseModel):
    key: str = Field("", max_length=200)  # empty: remove the key


@router.get("/integrations")
async def integrations(_: Admin, rt: RuntimeDep) -> IntegrationsOut:
    return IntegrationsOut(
        curseforge_api_key_set=await rt.secrets.is_set(SecretSetting.CURSEFORGE_API_KEY),
        public_address=rt.public_address.manual,
        detected_public_ip=rt.public_address.detected,
    )


@router.put("/integrations/curseforge", status_code=204)
async def set_curseforge_key(body: KeyIn, _: Admin, rt: RuntimeDep) -> None:
    await rt.secrets.set(SecretSetting.CURSEFORGE_API_KEY, body.key.strip() or None)


class AddressIn(BaseModel):
    address: str = Field("", max_length=253)  # empty: back to auto-detection


@router.put("/integrations/public-address", status_code=204)
async def set_public_address(body: AddressIn, _: Admin, rt: RuntimeDep) -> None:
    await rt.public_address.set_manual(body.address.strip() or None)
    rt.bus.publish("settings.public_address_updated", target=body.address.strip() or "auto")
