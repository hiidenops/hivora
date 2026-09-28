"""Host firewall routes (/api/v1/host-firewall): admin only, changes need a fresh TOTP."""

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hivora.core.errors import PermissionDeniedError
from hivora.hostfw.service import HostFirewall
from hivora.web.deps import Admin, Principal, RuntimeDep

router = APIRouter(tags=["host-firewall"])


class TotpRequiredError(PermissionDeniedError):
    code = "totp_required"


class AgentIn(BaseModel):
    enabled: bool


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class RuleIn(BaseModel):
    action: Literal["allow", "deny", "limit"]
    port: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp", "any"] = "tcp"
    source: str = Field(default="any", max_length=64)  # IP, network, or "any"


class UfwIn(BaseModel):
    enabled: bool
    keep_ssh: bool = True  # allow SSH (22/tcp, rate-limited) before turning UFW on


class JailIpIn(BaseModel):
    ip: str = Field(max_length=45)
    ban: bool = False


class DoneOut(BaseModel):
    output: str


def fw(rt: RuntimeDep) -> HostFirewall:
    return rt.hostfw


def confirmed(principal: Principal, rt: RuntimeDep) -> None:
    """Host changes need a TOTP code confirmed in the last minutes (like the console)."""
    if not rt.auth.recently_confirmed(principal.session_id, principal.totp_enabled):
        raise TotpRequiredError("confirm with a TOTP code first")


@router.get("")
async def state(_: Admin, rt: RuntimeDep, fresh: bool = False) -> dict[str, Any]:
    return asdict(await fw(rt).state(fresh=fresh))


@router.post("/confirm", status_code=204)
async def confirm(body: CodeIn, principal: Admin, rt: RuntimeDep) -> None:
    await rt.auth.confirm_console(principal.user_id, principal.session_id, body.code)


@router.put("/agent", status_code=204)
async def agent(body: AgentIn, principal: Admin, rt: RuntimeDep) -> None:
    confirmed(principal, rt)
    await fw(rt).set_agent(body.enabled)


@router.post("/ufw/rules")
async def add_rule(body: RuleIn, principal: Admin, rt: RuntimeDep) -> DoneOut:
    confirmed(principal, rt)
    return DoneOut(output=await fw(rt).ufw_rule(body.action, body.port, body.protocol, body.source))


@router.delete("/ufw/rules/{number}")
async def delete_rule(number: int, principal: Admin, rt: RuntimeDep) -> DoneOut:
    confirmed(principal, rt)
    return DoneOut(output=await fw(rt).ufw_delete(number))


@router.put("/ufw")
async def ufw(body: UfwIn, principal: Admin, rt: RuntimeDep) -> DoneOut:
    confirmed(principal, rt)
    return DoneOut(output=await fw(rt).ufw_enable(body.enabled, keep_ssh=body.keep_ssh))


@router.post("/fail2ban/{jail}")
async def jail_ip(jail: str, body: JailIpIn, principal: Admin, rt: RuntimeDep) -> DoneOut:
    confirmed(principal, rt)
    return DoneOut(output=await fw(rt).jail_ip(jail, body.ip, ban=body.ban))
