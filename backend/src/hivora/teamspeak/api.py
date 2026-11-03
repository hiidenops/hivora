"""TeamSpeak routes (/api/v1/apps/{id}/teamspeak/...): a server deployed from the template."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.core.errors import PermissionDeniedError
from hivora.teamspeak.jail import TeamSpeakJails
from hivora.teamspeak.service import MAX_SLOTS, TeamSpeak
from hivora.web.deps import Admin, Operator, Principal, RuntimeDep, Viewer

router = APIRouter(tags=["teamspeak"])


class TotpRequiredError(PermissionDeniedError):
    code = "totp_required"


def _fresh_totp(principal: Principal, rt: Any) -> None:
    if not rt.auth.recently_confirmed(principal.session_id, principal.totp_enabled):
        raise TotpRequiredError("confirm with a TOTP code first")


def ts(rt: RuntimeDep) -> TeamSpeak:
    return TeamSpeak(sessions=rt.sessions, apps=rt.apps, gateway=rt.gateway, bus=rt.bus)


def jails(rt: RuntimeDep) -> TeamSpeakJails:
    return TeamSpeakJails(
        sessions=rt.sessions, fw=rt.hostfw, bus=rt.bus, volumes_root=rt.settings.volumes_root
    )


class TsInfoOut(BaseModel):
    name: str
    welcome: str
    max_clients: int
    online: int
    version: str
    uptime_s: int
    password: bool  # a server password is set (its value is never read)
    log_clients: bool  # connections written to the server's log (the history)


class TsClientOut(BaseModel):
    clid: int
    name: str
    ip: str | None
    country: str | None
    connected_at: int | None
    idle_s: int


class TsBanOut(BaseModel):
    id: int
    ip: str | None
    name: str | None
    uid: str | None
    reason: str
    created: int
    duration_s: int
    by: str


class TsLogEntryOut(BaseModel):
    ts: str
    event: str
    name: str | None
    ip: str | None
    reason: str | None


class TsAdminKeyOut(BaseModel):
    created: int
    description: str


class TsNewKeyOut(BaseModel):
    key: str  # shown once


class TsSettingsIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    welcome: str = Field(default="", max_length=1024)
    max_clients: int = Field(ge=1, le=MAX_SLOTS)
    log_clients: bool = True


class TsPasswordIn(BaseModel):
    password: str = Field(default="", max_length=64)  # empty: no password


class TsBanIn(BaseModel):
    ip: str | None = Field(default=None, max_length=45)
    clid: int | None = None
    minutes: int = Field(default=0, ge=0, le=525_600)  # 0: forever
    reason: str = Field(default="", max_length=80)


class TsKickIn(BaseModel):
    reason: str = Field(default="", max_length=80)


class TsMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1024)


class TsJailSettings(BaseModel):
    maxretry: int = Field(ge=1, le=1000)
    findtime: str = Field(max_length=12)
    bantime: str = Field(max_length=12)


class TsJailIn(BaseModel):
    enabled: bool
    settings: TsJailSettings | None = None


class TsJailOut(BaseModel):
    agent: bool  # the host agent is on (needed)
    enabled: bool
    settings: TsJailSettings
    banned: list[str]
    failed: int
    jail: str
    matched: int | None = None  # lines of the log the filter recognises (on)


class TsUnbanIn(BaseModel):
    ip: str = Field(max_length=45)


@router.get("/{app_id}/teamspeak")
async def info(app_id: int, _: Viewer, rt: RuntimeDep) -> TsInfoOut:
    return TsInfoOut(**await ts(rt).info(app_id))


@router.put("/{app_id}/teamspeak", status_code=204)
async def edit(app_id: int, body: TsSettingsIn, _: Operator, rt: RuntimeDep) -> None:
    await ts(rt).edit(
        app_id,
        name=body.name,
        welcome=body.welcome,
        max_clients=body.max_clients,
        log_clients=body.log_clients,
    )


@router.put("/{app_id}/teamspeak/password", status_code=204)
async def password(app_id: int, body: TsPasswordIn, principal: Admin, rt: RuntimeDep) -> None:
    """The server password (admin and a recent TOTP)."""
    _fresh_totp(principal, rt)
    await ts(rt).set_password(app_id, body.password or None)


@router.get("/{app_id}/teamspeak/clients")
async def clients(app_id: int, _: Viewer, rt: RuntimeDep) -> list[TsClientOut]:
    return [TsClientOut(**asdict(c)) for c in await ts(rt).clients(app_id)]


@router.post("/{app_id}/teamspeak/clients/{clid}/kick", status_code=204)
async def kick(app_id: int, clid: int, body: TsKickIn, _: Operator, rt: RuntimeDep) -> None:
    await ts(rt).kick(app_id, clid, body.reason)


@router.post("/{app_id}/teamspeak/message", status_code=204)
async def message(app_id: int, body: TsMessageIn, _: Operator, rt: RuntimeDep) -> None:
    await ts(rt).message(app_id, body.text)


@router.get("/{app_id}/teamspeak/history")
async def history(app_id: int, _: Viewer, rt: RuntimeDep) -> list[TsLogEntryOut]:
    return [TsLogEntryOut(**asdict(e)) for e in await ts(rt).history(app_id)]


@router.get("/{app_id}/teamspeak/bans")
async def bans(app_id: int, _: Viewer, rt: RuntimeDep) -> list[TsBanOut]:
    return [TsBanOut(**asdict(b)) for b in await ts(rt).bans(app_id)]


@router.post("/{app_id}/teamspeak/bans", status_code=204)
async def ban(app_id: int, body: TsBanIn, _: Operator, rt: RuntimeDep) -> None:
    await ts(rt).ban(app_id, ip=body.ip, clid=body.clid, minutes=body.minutes, reason=body.reason)


@router.delete("/{app_id}/teamspeak/bans/{ban_id}", status_code=204)
async def unban(app_id: int, ban_id: int, _: Operator, rt: RuntimeDep) -> None:
    await ts(rt).unban(app_id, ban_id)


@router.get("/{app_id}/teamspeak/admin-keys")
async def admin_keys(app_id: int, _: Admin, rt: RuntimeDep) -> list[TsAdminKeyOut]:
    return [TsAdminKeyOut(**asdict(k)) for k in await ts(rt).admin_keys(app_id)]


@router.post("/{app_id}/teamspeak/admin-keys")
async def renew_admin_key(app_id: int, principal: Admin, rt: RuntimeDep) -> TsNewKeyOut:
    """A new admin key, the unused ones deleted (admin and a recent TOTP)."""
    _fresh_totp(principal, rt)
    return TsNewKeyOut(key=await ts(rt).renew_admin_key(app_id))


@router.get("/{app_id}/teamspeak/jail")
async def jail(app_id: int, _: Admin, rt: RuntimeDep) -> TsJailOut:
    slug = await ts(rt).slug(app_id)
    j = jails(rt)
    out = TsJailOut(**await j.state(slug))
    if out.enabled and out.agent:
        out.matched = await j.matches(slug)
    return out


@router.put("/{app_id}/teamspeak/jail", status_code=204)
async def set_jail(app_id: int, body: TsJailIn, _: Admin, rt: RuntimeDep) -> None:
    slug = await ts(rt).slug(app_id)
    values = (body.settings.model_dump() if body.settings else {}) if body.enabled else None
    await jails(rt).set(slug, values)


@router.post("/{app_id}/teamspeak/jail/unban", status_code=204)
async def jail_unban(app_id: int, body: TsUnbanIn, _: Admin, rt: RuntimeDep) -> None:
    await jails(rt).unban(await ts(rt).slug(app_id), body.ip)
