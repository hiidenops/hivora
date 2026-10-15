"""HTTP routes of the system module."""

import platform
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora import __version__
from hivora.system.releases import Channel
from hivora.system.secrets import SecretSetting
from hivora.system.status import Level, SystemStatus, worst
from hivora.web.deps import Admin, RuntimeDep, Viewer

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    version: str
    first_start: bool  # admin/admin still unchanged: the login page shows the hint
    source_url: str  # this version's source code (AGPL-3.0), shown before any login


class SystemInfo(BaseModel):
    version: str
    docker_version: str | None
    arch: str
    python: str


@router.get("/health")
async def health(rt: RuntimeDep) -> Health:
    """Public: used by the container healthcheck and the login page."""
    return Health(status="ok", version=__version__, first_start=await rt.auth.first_start(),
                  source_url=rt.settings.source_url)  # fmt: skip


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


class CheckOut(BaseModel):
    id: str  # version, database, disk, docker, jobs, panel_backup, exposure, tls, admin_vpn
    level: Level
    values: dict[str, Any]  # plain facts (sizes, dates, counts, addresses), never a secret


class StatusOut(BaseModel):
    worst: Level
    access: str  # how the panel is reached (install.env, HIVORA_ACCESS)
    checks: list[CheckOut]


@router.get("/status")
async def status(_: Admin, rt: RuntimeDep, deep: bool = False) -> StatusOut:
    """The panel's health, read only; ``deep``: also check the database (slower)."""
    status = SystemStatus(settings=rt.settings, sessions=rt.sessions, gateway=rt.gateway,
                          admin_vpn=rt.admin_vpn, clock=rt.clock)  # fmt: skip
    checks = await status.checks(deep=deep)
    out = [CheckOut(id=c.id, level=c.level, values=c.values) for c in checks]
    return StatusOut(worst=worst(checks), access=rt.settings.access, checks=out)


class ReleaseOut(BaseModel):
    tag: str  # v0.2.0
    version: str  # 0.2.0
    date: str | None
    url: str | None  # the release page
    notes: str  # plain text, never rendered
    prerelease: bool


class ReleasesOut(BaseModel):
    enabled: bool  # check for new versions (Settings; on by default)
    channel: Channel  # stable, or pre (release candidates too)
    available: bool  # the source is a GitHub repository (else: no check possible)
    current: str
    current_notes: str | None  # the installed version's CHANGELOG.md section
    latest: ReleaseOut | None
    newer: bool
    command: str | None  # the release's installer, to copy (the update itself: M13)
    checked_at: datetime | None
    error: str | None  # offline, rate_limited, not_found, unavailable


class ReleasePrefsIn(BaseModel):
    enabled: bool
    channel: Channel


@router.get("/releases")
async def releases(_: Admin, rt: RuntimeDep, refresh: bool = False) -> ReleasesOut:
    """The latest version of the channel (GitHub Releases, cached 12 h; nothing when off)."""
    return ReleasesOut(**await rt.releases.view(refresh=refresh))


@router.put("/releases/settings", status_code=204)
async def set_release_prefs(body: ReleasePrefsIn, _: Admin, rt: RuntimeDep) -> None:
    await rt.releases.set_prefs(body.enabled, body.channel)
    rt.bus.publish("settings.releases_updated", target=body.channel, enabled=body.enabled)


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
