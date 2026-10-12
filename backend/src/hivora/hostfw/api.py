"""Host firewall routes (/api/v1/host-firewall): admin only, changes need a fresh TOTP."""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from hivora.apps.api.common import JobRef, job_ref
from hivora.core.errors import PermissionDeniedError
from hivora.hostfw.blocking import Blocked
from hivora.hostfw.connections import connections, request_conntrack
from hivora.hostfw.routing import MAX_METRIC
from hivora.hostfw.service import (
    HostFirewall,
    jail_settings,
    listening,
    routes,
    save_jails,
)
from hivora.hostfw.static_routes import Listed
from hivora.web.deps import Admin, Principal, RuntimeDep, client_ip

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


class JailIn(BaseModel):
    enabled: bool = True
    maxretry: int | None = Field(default=None, ge=1, le=1000)
    bantime: str | None = Field(default=None, max_length=12)  # 600, 10m, 1h, 1d, -1
    findtime: str | None = Field(default=None, max_length=12)


class JailsIn(BaseModel):
    jails: dict[str, JailIn] = Field(max_length=50)


@router.get("/listening")
async def open_ports(_: Admin, rt: RuntimeDep) -> list[dict[str, Any]]:
    """What listens on the host, what opens it, and what UFW does about it."""
    return await listening(fw(rt))


@router.get("/connections")
async def inbound_connections(_: Admin, rt: RuntimeDep) -> dict[str, Any]:
    """Who is connected to the host now, per remote address (host services by ``ss``,
    Docker apps by ``conntrack`` when the host has it). Read only."""
    return await connections(fw(rt))


@router.post("/connections/conntrack", status_code=202)
async def install_conntrack(principal: Admin, rt: RuntimeDep) -> JobRef:
    """Install conntrack on the host (Debian, Ubuntu: apt-get), by a job: the apps'
    connections become visible. Like every host change: admin and a recent TOTP."""
    confirmed(principal, rt)
    return job_ref(await request_conntrack(fw(rt), rt.jobs))


@router.get("/routes")
async def host_routes(_: Admin, rt: RuntimeDep) -> dict[str, Any]:
    """The host's routing table (read-only) and the ports Docker forwards to apps."""
    forwards = [
        {"port": p.host_port, "protocol": p.protocol, "address": p.host_ip or "0.0.0.0",  # noqa: S104
         "app": c.labels.get("io.hivora.app") or c.name, "container_port": p.container_port}
        for c in rt.state.store.containers() for p in c.ports if p.host_port
    ]  # fmt: skip
    unique = {(f["port"], f["protocol"], f["address"]): f for f in forwards}
    ordered = sorted(unique.values(), key=lambda f: int(str(f["port"])))
    return {"routes": await routes(fw(rt)), "forwards": ordered}


@router.get("/fail2ban/settings")
async def get_jails(_: Admin, rt: RuntimeDep) -> dict[str, dict[str, str]]:
    return await jail_settings(fw(rt))


@router.put("/fail2ban/settings")
async def put_jails(body: JailsIn, principal: Admin, rt: RuntimeDep) -> DoneOut:
    """Writes /etc/fail2ban/jail.d/hivora.local, then reloads fail2ban."""
    confirmed(principal, rt)
    jails = {name: j.model_dump(exclude_none=True) for name, j in body.jails.items()}
    return DoneOut(output=await save_jails(fw(rt), jails))


class BlockIn(BaseModel):
    address: str = Field(max_length=45)
    note: str | None = Field(default=None, max_length=200)


class BlockedOut(BaseModel):
    address: str
    note: str | None
    created_by: int | None
    created_at: datetime


def blocked_out(b: Blocked) -> BlockedOut:
    return BlockedOut(address=b.address, note=b.note, created_by=b.created_by,
                      created_at=b.created_at)  # fmt: skip


@router.get("/blocked")
async def blocked(_: Admin, rt: RuntimeDep) -> list[BlockedOut]:
    """The addresses blocked on the host and its Docker apps (the intention)."""
    return [blocked_out(b) for b in await rt.blocking.listing()]


@router.post("/blocked", status_code=202)
async def block(body: BlockIn, request: Request, principal: Admin, rt: RuntimeDep) -> JobRef:
    """Block an address for the host and its apps (HIVORA-BLOCK, by a job). Never the
    address of the request itself, of the host, or of a container."""
    confirmed(principal, rt)
    return job_ref(await rt.blocking.block(body.address, body.note, requester=client_ip(request),
                                           user_id=principal.user_id))  # fmt: skip


@router.delete("/blocked/{address}", status_code=202)
async def unblock(address: str, principal: Admin, rt: RuntimeDep) -> JobRef:
    confirmed(principal, rt)
    return job_ref(await rt.blocking.unblock(address))


class StaticRouteIn(BaseModel):
    destination: str = Field(max_length=18)  # an IPv4 network, e.g. 10.8.0.0/24
    gateway: str = Field(max_length=15)
    dev: str | None = Field(default=None, max_length=15)
    metric: int | None = Field(default=None, ge=0, le=MAX_METRIC)
    note: str | None = Field(default=None, max_length=200)


class StaticRouteOut(BaseModel):
    id: int
    destination: str
    gateway: str
    dev: str | None
    metric: int | None
    note: str | None
    created_by: int | None
    created_at: datetime
    applied: bool | None  # set on the host now; None: unknown (agent off, table unreadable)


def static_route_out(r: Listed) -> StaticRouteOut:
    return StaticRouteOut(id=r.id, destination=r.destination, gateway=r.gateway, dev=r.dev,
                          metric=r.metric, note=r.note, created_by=r.created_by,
                          created_at=r.created_at, applied=r.applied)  # fmt: skip


@router.get("/static-routes")
async def static_routes(_: Admin, rt: RuntimeDep) -> list[StaticRouteOut]:
    """The host's static IPv4 routes kept by Hivora (marked proto 241), each with whether
    it is set on the host now."""
    return [static_route_out(r) for r in await rt.static_routes.listing()]


@router.post("/static-routes", status_code=202)
async def add_static_route(body: StaticRouteIn, request: Request, principal: Admin,
                           rt: RuntimeDep) -> JobRef:  # fmt: skip
    """Add a route (a job sets it). Refused when it could cut the host off: the default
    route, a connected network, the requester's own address, a gateway out of reach."""
    confirmed(principal, rt)
    job = await rt.static_routes.add(body.destination, body.gateway, dev=body.dev,
                                     metric=body.metric, note=body.note,
                                     requester=client_ip(request),
                                     user_id=principal.user_id)  # fmt: skip
    return job_ref(job)


@router.delete("/static-routes/{route_id}", status_code=202)
async def remove_static_route(route_id: int, principal: Admin, rt: RuntimeDep) -> JobRef:
    confirmed(principal, rt)
    return job_ref(await rt.static_routes.remove(route_id))
